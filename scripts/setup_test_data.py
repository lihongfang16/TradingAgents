#!/usr/bin/env python3
"""Test data setup script for K-line signal overlay development.

This script creates test watchlist entries and analysis history
for testing the signal overlay and trajectory visualization features.
"""

import os
import sys
from datetime import datetime, timedelta

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from webapi.config.database import SessionLocal
from webapi.models.database import Watchlist, WatchlistAnalysis


def setup_test_data():
    """Create test data for K-line signal overlay testing."""
    db = SessionLocal()
    
    try:
        # Check if test data already exists
        existing = db.query(Watchlist).filter(Watchlist.symbol == '000001').first()
        if existing:
            print(f"Test data already exists (watchlist_id={existing.id})")
            print(f"watchlist_id={existing.id}")
            return existing.id
        
        # Create watchlist entry for stock 000001 (平安银行)
        watchlist = Watchlist(
            symbol='000001',
            name='平安银行',
            exchange='CN',
            added_at=datetime.utcnow(),
            is_active='Y',
            turning_detection_enabled='N',
            confidence_jump_threshold='0.15',
            last_analysis_at=datetime.utcnow(),
            last_signal='BUY',
            last_confidence='0.85',
            last_risk_level='medium',
        )
        db.add(watchlist)
        db.flush()  # Get the ID
        
        print(f"Created watchlist entry: id={watchlist.id}, symbol={watchlist.symbol}")
        
        # Create analysis history with various signals
        base_time = datetime.utcnow() - timedelta(days=7)
        
        analyses = [
            # BUY signal at price 10.0 (entry)
            {
                'analysis_type': 'quick',
                'triggered_by': 'manual',
                'created_at': base_time,
                'completed_at': base_time + timedelta(minutes=5),
                'signal': 'BUY',
                'confidence': '0.85',
                'risk_level': 'medium',
                'price': 10.0,
            },
            # HOLD signal
            {
                'analysis_type': 'quick',
                'triggered_by': 'scheduled',
                'created_at': base_time + timedelta(days=1),
                'completed_at': base_time + timedelta(days=1, minutes=5),
                'signal': 'HOLD',
                'confidence': '0.60',
                'risk_level': 'low',
                'price': 10.5,
            },
            # SELL signal at price 12.0 (profitable exit)
            {
                'analysis_type': 'quick',
                'triggered_by': 'manual',
                'created_at': base_time + timedelta(days=2),
                'completed_at': base_time + timedelta(days=2, minutes=5),
                'signal': 'SELL',
                'confidence': '0.90',
                'risk_level': 'medium',
                'price': 12.0,
            },
            # Another BUY at price 11.0
            {
                'analysis_type': 'quick',
                'triggered_by': 'scheduled',
                'created_at': base_time + timedelta(days=3),
                'completed_at': base_time + timedelta(days=3, minutes=5),
                'signal': 'BUY',
                'confidence': '0.75',
                'risk_level': 'medium',
                'price': 11.0,
            },
            # SELL at price 10.5 (loss)
            {
                'analysis_type': 'quick',
                'triggered_by': 'manual',
                'created_at': base_time + timedelta(days=4),
                'completed_at': base_time + timedelta(days=4, minutes=5),
                'signal': 'SELL',
                'confidence': '0.80',
                'risk_level': 'high',
                'price': 10.5,
            },
            # Another BUY for trajectory testing
            {
                'analysis_type': 'quick',
                'triggered_by': 'scheduled',
                'created_at': base_time + timedelta(days=5),
                'completed_at': base_time + timedelta(days=5, minutes=5),
                'signal': 'BUY',
                'confidence': '0.88',
                'risk_level': 'low',
                'price': 10.8,
            },
            # Final SELL (profit)
            {
                'analysis_type': 'quick',
                'triggered_by': 'manual',
                'created_at': base_time + timedelta(days=6),
                'completed_at': base_time + timedelta(days=6, minutes=5),
                'signal': 'SELL',
                'confidence': '0.92',
                'risk_level': 'medium',
                'price': 11.5,
            },
        ]
        
        for data in analyses:
            analysis = WatchlistAnalysis(
                watchlist_id=watchlist.id,
                analysis_type=data['analysis_type'],
                triggered_by=data['triggered_by'],
                created_at=data['created_at'],
                completed_at=data['completed_at'],
                signal=data['signal'],
                confidence=data['confidence'],
                risk_level=data['risk_level'],
                price=data['price'],
                error_message=None,
                is_turning_point='N',
            )
            db.add(analysis)
        
        db.commit()
        
        print(f"Created {len(analyses)} analysis records")
        print(f"Test data setup complete! watchlist_id={watchlist.id}")
        print(f"watchlist_id={watchlist.id}")
        print("\nSignal sequence for trajectory testing:")
        print("  BUY(10.0) → HOLD(10.5) → SELL(12.0) [PROFIT +20%]")
        print("  BUY(11.0) → SELL(10.5) [LOSS -4.5%]")
        print("  BUY(10.8) → SELL(11.5) [PROFIT +6.5%]")
        
        return watchlist.id
        
    except Exception as e:
        db.rollback()
        print(f"Error setting up test data: {e}")
        raise
    finally:
        db.close()


def cleanup_test_data():
    """Remove test data."""
    db = SessionLocal()
    
    try:
        # Find test watchlist
        watchlist = db.query(Watchlist).filter(Watchlist.symbol == '000001').first()
        if watchlist:
            # Delete associated analyses
            db.query(WatchlistAnalysis).filter(
                WatchlistAnalysis.watchlist_id == watchlist.id
            ).delete()
            # Delete watchlist
            db.delete(watchlist)
            db.commit()
            print(f"Cleaned up test data for watchlist_id={watchlist.id}")
        else:
            print("No test data found")
    except Exception as e:
        db.rollback()
        print(f"Error cleaning up test data: {e}")
        raise
    finally:
        db.close()


if __name__ == '__main__':
    import argparse
    
    parser = argparse.ArgumentParser(description='Setup test data for K-line signal overlay')
    parser.add_argument('--cleanup', action='store_true', help='Remove test data')
    
    args = parser.parse_args()
    
    if args.cleanup:
        cleanup_test_data()
    else:
        setup_test_data()
