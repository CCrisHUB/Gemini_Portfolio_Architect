#run_tests.py
#"""
#Golden Test Harness for Deep Freeze Sweep
#Date: 2026-09-16
#Role: Validates the 30-day archival sweep logic without polluting production directories.
#"""
import os
import time
import shutil
import alu_utils

def setup_test_environment():
    """Creates a mock directory structure for testing."""
    base_test_dir = "test_env"
    archive_dir = os.path.join(base_test_dir, "mock_archive")
    deep_archive_dir = os.path.join(base_test_dir, "mock_deep_archive")
    
    if os.path.exists(base_test_dir):
        shutil.rmtree(base_test_dir)
        
    os.makedirs(archive_dir)
    os.makedirs(deep_archive_dir)
    
    # Create a "new" file (timestamp = now)
    new_file_path = os.path.join(archive_dir, "recent_file.txt")
    with open(new_file_path, 'w') as f:
        f.write("This file is new.")
        
    # Create an "old" file (timestamp = 35 days ago)
    old_file_path = os.path.join(archive_dir, "old_file.txt")
    with open(old_file_path, 'w') as f:
        f.write("This file is old.")
        
    # Modify the timestamp of the old file
    thirty_five_days_sec = 35 * 24 * 60 * 60
    old_time = time.time() - thirty_five_days_sec
    os.utime(old_file_path, (old_time, old_time))
    
    return base_test_dir, archive_dir, deep_archive_dir

def run_tests():
    print("=== RUNNING GOLDEN TEST HARNESS ===")
    base_test_dir, archive_dir, deep_archive_dir = setup_test_environment()
    
    try:
        print("1. Executing Deep Freeze Sweep...")
        moved_files = alu_utils.execute_deep_freeze_sweep(archive_dir, deep_archive_dir)
        
        print(f"2. Files moved: {moved_files}")
        
        # Assertions
        assert "old_file.txt" in moved_files, "FAIL: Old file was not moved."
        assert "recent_file.txt" not in moved_files, "FAIL: Recent file was incorrectly moved."
        
        assert not os.path.exists(os.path.join(archive_dir, "old_file.txt")), "FAIL: Old file still exists in source."
        assert os.path.exists(os.path.join(archive_dir, "recent_file.txt")), "FAIL: Recent file missing from source."
        
        assert os.path.exists(os.path.join(deep_archive_dir, "old_file.txt")), "FAIL: Old file not found in destination."
        
        print("\033[92m[SUCCESS] All assertions passed. Sweep logic is deterministic and safe.\033[0m")
        
    except AssertionError as e:
        print(f"\033[91m{e}\033[0m")
    finally:
        print("3. Cleaning up test environment...")
        if os.path.exists(base_test_dir):
            shutil.rmtree(base_test_dir)
        print("=== TEST COMPLETE ===")

if __name__ == "__main__":
    run_tests()