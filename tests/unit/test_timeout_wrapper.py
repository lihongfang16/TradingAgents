"""Unit tests for TimeoutWrapper.

Tests verify:
1. Timeout fires when LLM hangs (no data)
2. Timeout does NOT fire when chunks keep coming (even if slow)
3. bind_tools() is properly proxied
4. Both sync and async interfaces work
"""

import time
import pytest
from unittest.mock import MagicMock, patch
import sys
import os

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

from tradingagents.llm_clients.timeout_wrapper import TimeoutWrapper, wrap_with_timeout


class TestTimeoutWrapperBasic:
    """Basic functionality tests."""
    
    def test_wrapper_creation(self):
        """Test that wrapper can be created with LLM instance."""
        mock_llm = MagicMock()
        wrapper = TimeoutWrapper(mock_llm, nodata_timeout_seconds=5)
        
        assert wrapper.llm == mock_llm
        assert wrapper.nodata_timeout_seconds == 5
    
    def test_wrap_with_timeout_convenience(self):
        """Test convenience function."""
        mock_llm = MagicMock()
        wrapper = wrap_with_timeout(mock_llm, 10)
        
        assert isinstance(wrapper, TimeoutWrapper)
        assert wrapper.nodata_timeout_seconds == 10
    
    def test_attribute_proxy(self):
        """Test that attributes are proxied to wrapped LLM."""
        mock_llm = MagicMock()
        mock_llm.some_attribute = "test_value"
        mock_llm.model_name = "gpt-4"
        
        wrapper = TimeoutWrapper(mock_llm)
        
        assert wrapper.some_attribute == "test_value"
        assert wrapper.model_name == "gpt-4"


class TestTimeoutWrapperBindTools:
    """Tests for bind_tools proxy."""
    
    def test_bind_tools_proxied(self):
        """Test that bind_tools is called on wrapped LLM."""
        mock_llm = MagicMock()
        mock_bound = MagicMock()
        mock_llm.bind_tools.return_value = mock_bound
        
        wrapper = TimeoutWrapper(mock_llm, nodata_timeout_seconds=5)
        tools = [{"name": "test_tool"}]
        
        result = wrapper.bind_tools(tools)
        
        # Verify bind_tools was called on original LLM
        mock_llm.bind_tools.assert_called_once_with(tools)
        
        # Verify result is a new TimeoutWrapper
        assert isinstance(result, TimeoutWrapper)
        assert result.llm == mock_bound
        assert result.nodata_timeout_seconds == 5
    
    def test_bind_tools_preserves_timeout(self):
        """Test that timeout setting is preserved in bound wrapper."""
        mock_llm = MagicMock()
        mock_bound = MagicMock()
        mock_llm.bind_tools.return_value = mock_bound
        
        wrapper = TimeoutWrapper(mock_llm, nodata_timeout_seconds=60)
        bound_wrapper = wrapper.bind_tools([])
        
        assert bound_wrapper.nodata_timeout_seconds == 60


class TestTimeoutWrapperSync:
    """Tests for synchronous invoke."""
    
    def test_invoke_success_no_timeout(self):
        """Test successful invoke without timeout."""
        mock_llm = MagicMock()
        mock_llm.invoke.return_value = {"content": "Hello"}
        
        wrapper = TimeoutWrapper(mock_llm, nodata_timeout_seconds=5)
        result = wrapper.invoke("test prompt")
        
        assert result == {"content": "Hello"}
        mock_llm.invoke.assert_called_once_with("test prompt", None)
    
    def test_invoke_times_out_when_hangs(self):
        """Test that TimeoutError is raised when LLM hangs."""
        mock_llm = MagicMock()
        
        def slow_invoke(*args, **kwargs):
            time.sleep(10)  # Hang for 10 seconds
            return {"content": "too late"}
        
        mock_llm.invoke = slow_invoke
        
        wrapper = TimeoutWrapper(mock_llm, nodata_timeout_seconds=1)
        
        start = time.time()
        with pytest.raises(TimeoutError) as exc_info:
            wrapper.invoke("test")
        elapsed = time.time() - start
        
        # Should timeout in ~1 second, not 10
        assert elapsed < 3
        assert "timed out" in str(exc_info.value).lower()
    
    def test_invoke_forwards_config_and_kwargs(self):
        """Test that config and kwargs are forwarded to LLM."""
        mock_llm = MagicMock()
        mock_llm.invoke.return_value = {"content": "OK"}
        
        wrapper = TimeoutWrapper(mock_llm)
        config = {"temperature": 0.5}
        
        wrapper.invoke("prompt", config=config, custom_arg="value")
        
        mock_llm.invoke.assert_called_once_with("prompt", config, custom_arg="value")


class TestTimeoutWrapperStreaming:
    """Tests for streaming with timeout."""
    
    def test_streaming_no_timeout_with_chunks(self):
        """Test that streaming doesn't timeout when chunks keep coming."""
        
        def mock_stream(*args, **kwargs):
            """Generator that yields chunks every 0.2s for 1s total."""
            for i in range(5):
                time.sleep(0.2)
                yield {"content": f"chunk {i}"}
        
        mock_llm = MagicMock()
        mock_llm.stream = mock_stream
        
        # 2 second timeout, but chunks come every 0.2s
        wrapper = TimeoutWrapper(mock_llm, nodata_timeout_seconds=2)
        
        chunks = list(wrapper.invoke("test", stream=True))
        
        assert len(chunks) == 5
        assert chunks[0] == {"content": "chunk 0"}
        assert chunks[4] == {"content": "chunk 4"}
    
    def test_streaming_times_out_no_chunks(self):
        """Test that streaming times out when no chunks received."""
        
        def mock_slow_stream(*args, **kwargs):
            """Generator that hangs without yielding."""
            time.sleep(10)
            yield {"content": "too late"}
        
        mock_llm = MagicMock()
        mock_llm.stream = mock_slow_stream
        
        wrapper = TimeoutWrapper(mock_llm, nodata_timeout_seconds=1)
        
        start = time.time()
        with pytest.raises(TimeoutError) as exc_info:
            # Consume the generator
            list(wrapper.invoke("test", stream=True))
        elapsed = time.time() - start
        
        assert elapsed < 3  # Should timeout quickly
        assert "timed out" in str(exc_info.value).lower()
        assert "streaming" in str(exc_info.value).lower()


class TestTimeoutWrapperAsync:
    """Tests for async ainvoke."""
    
    @pytest.mark.asyncio
    async def test_ainvoke_success_no_timeout(self):
        """Test successful async invoke without timeout."""
        mock_llm = MagicMock()
        mock_llm.ainvoke = MagicMock(return_value={"content": "Hello"})
        
        # Need to make it awaitable
        async def async_return(*args, **kwargs):
            return {"content": "Hello"}
        
        mock_llm.ainvoke = async_return
        
        wrapper = TimeoutWrapper(mock_llm, nodata_timeout_seconds=5)
        result = await wrapper.ainvoke("test prompt")
        
        assert result == {"content": "Hello"}
    
    @pytest.mark.asyncio
    async def test_ainvoke_times_out(self):
        """Test that async invoke times out when LLM hangs."""
        
        async def slow_ainvoke(*args, **kwargs):
            await asyncio.sleep(10)
            return {"content": "too late"}
        
        mock_llm = MagicMock()
        mock_llm.ainvoke = slow_ainvoke
        
        import asyncio
        wrapper = TimeoutWrapper(mock_llm, nodata_timeout_seconds=1)
        
        start = time.time()
        with pytest.raises(TimeoutError):
            await wrapper.ainvoke("test")
        elapsed = time.time() - start
        
        assert elapsed < 3  # Should timeout quickly


class TestTimeoutWrapperEdgeCases:
    """Edge case tests."""
    
    def test_error_propagation(self):
        """Test that LLM errors are properly propagated."""
        mock_llm = MagicMock()
        mock_llm.invoke.side_effect = ValueError("LLM error")
        
        wrapper = TimeoutWrapper(mock_llm)
        
        with pytest.raises(ValueError, match="LLM error"):
            wrapper.invoke("test")
    
    def test_default_timeout_value(self):
        """Test that default timeout is 120 seconds."""
        mock_llm = MagicMock()
        wrapper = TimeoutWrapper(mock_llm)
        
        assert wrapper.nodata_timeout_seconds == 120.0
    
    def test_custom_timeout_value(self):
        """Test custom timeout value."""
        mock_llm = MagicMock()
        wrapper = TimeoutWrapper(mock_llm, nodata_timeout_seconds=300)
        
        assert wrapper.nodata_timeout_seconds == 300


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
