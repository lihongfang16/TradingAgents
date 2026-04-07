"""Timeout wrapper for LangChain LLM clients with streaming heartbeat support.

This module provides a wrapper around LangChain LLM instances that implements
a "no-data timeout" - the timer resets whenever data chunks are received.
This is essential for streaming LLM responses where we want to allow slow
responses but timeout if the connection is completely hung.

Usage:
    from tradingagents.llm_clients.timeout_wrapper import TimeoutWrapper
    
    # Wrap an existing LLM instance
    wrapped_llm = TimeoutWrapper(
        llm_instance, 
        nodata_timeout_seconds=120
    )
    
    # Use normally - timeout applies to streaming and non-streaming calls
    result = wrapped_llm.invoke("prompt")
    
    # bind_tools() is proxied correctly
    bound = wrapped_llm.bind_tools(tools)
    result = bound.invoke("prompt with tool")

Implementation Notes:
    - Wraps both sync (invoke) and async (ainvoke) methods
    - Uses threading.Timer for timeout detection
    - Timer resets on each chunk received during streaming
    - Raises TimeoutError if no data for specified duration
    - Proxies all other methods via __getattr__ to maintain LLM interface
"""

import time
import threading
from typing import Any, Optional, Iterator, AsyncIterator, Callable
from unittest.mock import MagicMock


class TimeoutWrapper:
    """Wrapper that adds no-data timeout to LangChain LLM calls.
    
    This wrapper monitors LLM calls and raises TimeoutError if no data
    is received for the specified duration. For streaming calls, the
    timer resets on each chunk received.
    
    Attributes:
        llm: The wrapped LangChain LLM instance
        nodata_timeout_seconds: Seconds to wait before timing out on no data
        
    Example:
        >>> from langchain_openai import ChatOpenAI
        >>> llm = ChatOpenAI(model="gpt-4")
        >>> wrapped = TimeoutWrapper(llm, nodata_timeout_seconds=120)
        >>> result = wrapped.invoke("Hello")  # Times out if no response in 120s
    """
    
    def __init__(self, llm: Any, nodata_timeout_seconds: float = 120.0):
        """Initialize the timeout wrapper.
        
        Args:
            llm: The LangChain LLM instance to wrap
            nodata_timeout_seconds: Timeout duration if no data received
        """
        self.llm = llm
        self.nodata_timeout_seconds = nodata_timeout_seconds
        
    def __getattr__(self, name: str) -> Any:
        """Proxy attribute access to wrapped LLM.
        
        This allows the wrapper to transparently pass through all methods
        and attributes not explicitly handled (e.g., model info, config).
        """
        return getattr(self.llm, name)
    
    def bind_tools(self, tools: list, **kwargs) -> "TimeoutWrapper":
        """Bind tools to the LLM and return a new wrapped instance.
        
        This method wraps the bound runnable so that tool calls also
        have timeout protection applied.
        
        Args:
            tools: List of tools to bind to the LLM
            **kwargs: Additional binding arguments
            
        Returns:
            A new TimeoutWrapper wrapping the bound LLM
        """
        bound_llm = self.llm.bind_tools(tools, **kwargs)
        return TimeoutWrapper(bound_llm, self.nodata_timeout_seconds)
    
    def invoke(self, input: Any, config: Optional[dict] = None, **kwargs) -> Any:
        """Invoke the LLM with timeout protection.
        
        For non-streaming calls, the timeout applies to the entire call.
        For streaming calls, timeout resets on each chunk.
        
        Args:
            input: The input prompt/messages
            config: Optional LangChain config
            **kwargs: Additional invoke arguments
            
        Returns:
            The LLM response
            
        Raises:
            TimeoutError: If no data received for nodata_timeout_seconds
        """
        # Check if streaming is requested
        is_streaming = kwargs.get('stream', False)
        
        if is_streaming:
            # For streaming, we need to wrap the iterator
            return self._invoke_streaming(input, config, **kwargs)
        else:
            # For non-streaming, use a simple timeout
            return self._invoke_with_timeout(input, config, **kwargs)
    
    def _invoke_with_timeout(self, input: Any, config: Optional[dict], **kwargs) -> Any:
        """Execute invoke with a hard timeout.
        
        Uses threading to implement timeout for non-streaming calls.
        """
        result = [None]
        exception = [None]
        completed = threading.Event()
        
        def target():
            try:
                result[0] = self.llm.invoke(input, config, **kwargs)
            except Exception as e:
                exception[0] = e
            finally:
                completed.set()
        
        thread = threading.Thread(target=target)
        thread.start()
        
        # Wait with timeout
        if not completed.wait(timeout=self.nodata_timeout_seconds):
            # Timeout occurred
            # Note: We can't cleanly interrupt the thread, but we can raise
            # This is a limitation - the thread will continue in background
            raise TimeoutError(
                f"LLM call timed out after {self.nodata_timeout_seconds}s "
                f"(no response received)"
            )
        
        thread.join(timeout=1.0)  # Brief wait for cleanup
        
        if exception[0] is not None:
            raise exception[0]
            
        return result[0]
    
    def _invoke_streaming(self, input: Any, config: Optional[dict], **kwargs) -> Iterator[Any]:
        """Execute streaming invoke with per-chunk timeout.
        
        Yields chunks as they arrive, but resets timeout timer on each chunk.
        If no chunk received within timeout, raises TimeoutError.
        
        Uses a background thread to consume the stream, with a queue for
        chunks so the main thread can check timeout without blocking.
        """
        import queue
        
        chunk_queue = queue.Queue()
        done_event = threading.Event()
        exception_holder = [None]
        
        def consume_stream():
            """Background thread: consume stream and put chunks in queue."""
            try:
                stream_iter = self.llm.stream(input, config, **kwargs)
                for chunk in stream_iter:
                    chunk_queue.put(('chunk', chunk))
                chunk_queue.put(('done', None))
            except Exception as e:
                exception_holder[0] = e
                chunk_queue.put(('error', None))
            finally:
                done_event.set()
        
        # Start consumer thread
        consumer_thread = threading.Thread(target=consume_stream, daemon=True)
        consumer_thread.start()
        
        # Main thread: yield chunks with timeout
        last_chunk_time = time.time()
        
        while True:
            # Check if we've exceeded timeout since last chunk
            if time.time() - last_chunk_time > self.nodata_timeout_seconds:
                raise TimeoutError(
                    f"LLM streaming timed out after {self.nodata_timeout_seconds}s "
                    f"(no data chunk received)"
                )
            
            try:
                # Try to get next chunk with short timeout
                msg_type, chunk = chunk_queue.get(timeout=0.1)
                
                if msg_type == 'chunk':
                    # Got a chunk - reset timer and yield
                    last_chunk_time = time.time()
                    yield chunk
                elif msg_type == 'done':
                    # Stream complete
                    break
                elif msg_type == 'error':
                    # Exception in consumer thread
                    if exception_holder[0]:
                        raise exception_holder[0]
                    break
                    
            except queue.Empty:
                # No chunk available yet, loop and check timeout
                continue
        
        # Wait for consumer to finish
        consumer_thread.join(timeout=1.0)
    
    async def ainvoke(self, input: Any, config: Optional[dict] = None, **kwargs) -> Any:
        """Async invoke with timeout protection.
        
        Args:
            input: The input prompt/messages
            config: Optional LangChain config
            **kwargs: Additional invoke arguments
            
        Returns:
            The LLM response
            
        Raises:
            TimeoutError: If no data received for nodata_timeout_seconds
        """
        import asyncio
        
        is_streaming = kwargs.get('stream', False)
        
        if is_streaming:
            return self._ainvoke_streaming(input, config, **kwargs)
        else:
            try:
                return await asyncio.wait_for(
                    self.llm.ainvoke(input, config, **kwargs),
                    timeout=self.nodata_timeout_seconds
                )
            except asyncio.TimeoutError:
                raise TimeoutError(
                    f"LLM async call timed out after {self.nodata_timeout_seconds}s "
                    f"(no response received)"
                )
    
    async def _ainvoke_streaming(self, input: Any, config: Optional[dict], **kwargs) -> AsyncIterator[Any]:
        """Execute async streaming with per-chunk timeout.
        
        Uses asyncio to monitor timeout between chunks.
        """
        import asyncio
        
        stream_iter = self.llm.astream(input, config, **kwargs)
        
        async def chunk_generator():
            """Async generator with timeout monitoring."""
            while True:
                try:
                    # Try to get next chunk with timeout
                    chunk = await asyncio.wait_for(
                        stream_iter.__anext__(),
                        timeout=self.nodata_timeout_seconds
                    )
                    yield chunk
                except asyncio.TimeoutError:
                    raise TimeoutError(
                        f"LLM async streaming timed out after {self.nodata_timeout_seconds}s "
                        f"(no data chunk received)"
                    )
                except StopAsyncIteration:
                    break
        
        return chunk_generator()


# Convenience function for creating wrapped LLMs
def wrap_with_timeout(llm: Any, nodata_timeout_seconds: float = 120.0) -> TimeoutWrapper:
    """Wrap an LLM instance with timeout protection.
    
    This is a convenience function that creates a TimeoutWrapper.
    
    Args:
        llm: The LangChain LLM instance to wrap
        nodata_timeout_seconds: Timeout duration in seconds (default: 120)
        
    Returns:
        A TimeoutWrapper instance
        
    Example:
        >>> from langchain_openai import ChatOpenAI
        >>> llm = ChatOpenAI()
        >>> wrapped = wrap_with_timeout(llm, 60)  # 60 second timeout
    """
    return TimeoutWrapper(llm, nodata_timeout_seconds)
