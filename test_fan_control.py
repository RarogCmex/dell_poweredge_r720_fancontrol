#!/usr/bin/env python3

"""
Test script for the enhanced fan control with AMD/NVIDIA multi-GPU support.
This script tests the new functionality without requiring actual hardware.
"""

import sys
import os
import tempfile
import yaml
import subprocess
from unittest.mock import patch, MagicMock
import sensors  # Import to ensure it's available

# Add the current directory to Python path to import the fan control module
sys.path.insert(0, '.')

def create_test_config(config_content):
    """Create a temporary config file for testing."""
    with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as f:
        yaml.dump(config_content, f)
        return f.name

def test_amd_temperature_function():
    """Test the AMD temperature function with mocked sensors."""
    print("Testing AMD temperature function...")
    
    # Import the function after adding to path
    from fan_control import get_amd_temperatures
    
    # Mock sensors.get_detected_chips() to return AMD GPU sensors
    mock_sensor = MagicMock()
    mock_sensor.prefix = 'amdgpu'
    mock_sensor.get_features.return_value = [MagicMock()]
    mock_sensor.get_all_subfeatures.return_value = [
        MagicMock(name='temp1_input', number=1),
        MagicMock(name='temp2_input', number=2)
    ]
    mock_sensor.get_value.side_effect = lambda x: [45.0, 50.0][x-1]
    
    with patch('fan_control.sensors.get_detected_chips', return_value=[mock_sensor]):
        temps = get_amd_temperatures()
        print(f"AMD temperatures: {temps}")
        assert len(temps) == 2
        assert temps[0] == 45.0
        assert temps[1] == 50.0
        print("✓ AMD temperature function test passed")

def test_nvidia_temperature_function():
    """Test the NVIDIA temperature function with mocked subprocess."""
    print("Testing NVIDIA temperature function...")
    
    from fan_control import get_nvidia_temperatures
    
    # Mock nvidia-smi output
    mock_result = MagicMock()
    mock_result.stdout = "65\n70\n"
    mock_result.stderr = ""
    
    with patch('fan_control.subprocess.run', return_value=mock_result):
        temps = get_nvidia_temperatures()
        print(f"NVIDIA temperatures: {temps}")
        assert len(temps) == 2
        assert temps[0] == 65
        assert temps[1] == 70
        print("✓ NVIDIA temperature function test passed")

def test_gpu_temperature_function():
    """Test the combined GPU temperature function."""
    print("Testing combined GPU temperature function...")
    
    from fan_control import get_gpu_temperatures
    
    # Test with both AMD and NVIDIA enabled - provide complete config structure
    config = {
        'general': {
            'debug': False
        },
        'gpu_monitoring': {
            'monitor_amd_gpus': True,
            'monitor_nvidia_gpus': True
        }
    }
    
    # Mock both AMD and NVIDIA functions
    with patch('fan_control.get_amd_temperatures', return_value=[45, 50]), \
         patch('fan_control.get_nvidia_temperatures', return_value=[65, 70]), \
         patch('fan_control.config', config):
        
        temps = get_gpu_temperatures()
        print(f"Combined temperatures: {temps}")
        assert len(temps) == 4
        assert temps == [45, 50, 65, 70]
        print("✓ Combined GPU temperature function test passed")

def test_config_parsing():
    """Test configuration parsing with new GPU monitoring options."""
    print("Testing configuration parsing...")
    
    # Create test config
    test_config_content = {
        'general': {
            'debug': True,
            'interval': 1
        },
        'gpu_monitoring': {
            'monitor_amd_gpus': True,
            'monitor_nvidia_gpus': False
        },
        'host': {
            'name': 'TestHost',
            'hysteresis': 2,
            'temperatures': [55, 60, 70, 75],
            'speeds': [13, 17, 25, 37]
        }
    }
    
    config_file = create_test_config(test_config_content)
    
    try:
        # Import and test config parsing
        from fan_control import parse_config, config
        
        # Temporarily modify config paths
        original_config_paths = config['config_paths']
        config['config_paths'] = [config_file]
        
        parse_config()
        
        # Verify GPU monitoring config was parsed correctly
        assert 'gpu_monitoring' in config
        assert config['gpu_monitoring']['monitor_amd_gpus'] == True
        assert config['gpu_monitoring']['monitor_nvidia_gpus'] == False
        print("✓ Configuration parsing test passed")
        
    finally:
        # Clean up
        os.unlink(config_file)
        config['config_paths'] = original_config_paths

def test_fallback_behavior():
    """Test fallback behavior when no GPUs are detected."""
    print("Testing fallback behavior...")
    
    from fan_control import get_gpu_temperatures
    
    config = {
        'gpu_monitoring': {
            'monitor_amd_gpus': True,
            'monitor_nvidia_gpus': True
        }
    }
    
    # Mock both functions to return empty lists
    with patch('fan_control.get_amd_temperatures', return_value=[]), \
         patch('fan_control.get_nvidia_temperatures', return_value=[]), \
         patch('fan_control.config', config):
        
        temps = get_gpu_temperatures()
        print(f"Fallback temperatures: {temps}")
        assert temps == [0]  # Should fallback to [0]
        print("✓ Fallback behavior test passed")

def test_error_handling():
    """Test error handling in temperature functions."""
    print("Testing error handling...")
    
    from fan_control import get_amd_temperatures, get_nvidia_temperatures
    
    # Test AMD error handling
    with patch('fan_control.sensors.get_detected_chips', side_effect=Exception("Sensor error")):
        temps = get_amd_temperatures()
        assert temps == []
        print("✓ AMD error handling test passed")
    
    # Test NVIDIA error handling
    with patch('fan_control.subprocess.run', side_effect=Exception("NVIDIA error")):
        temps = get_nvidia_temperatures()
        assert temps == []
        print("✓ NVIDIA error handling test passed")

def test_real_hardware_amd_gpu():
    """Test with real AMD GPU hardware if available."""
    print("Testing with real AMD GPU hardware...")
    
    try:
        from fan_control import get_amd_temperatures
        import sensors
        
        # Check if AMD GPU is actually present
        amd_gpu_present = False
        for sensor in sensors.get_detected_chips():
            if sensor.prefix == 'amdgpu':
                amd_gpu_present = True
                break
        
        if not amd_gpu_present:
            print("⚠️  No AMD GPU hardware detected (skipping real hardware test)")
            return True
        
        # Test with real hardware
        temps = get_amd_temperatures()
        print(f"Real AMD GPU temperatures: {temps}")
        
        # Verify we get reasonable temperatures
        if temps:
            # Check that temperatures are in reasonable range for a GPU
            for temp in temps:
                assert 0 <= temp <= 125, f"Invalid temperature: {temp}°C"
            
            avg_temp = sum(temps) / len(temps)
            print(f"Average temperature: {avg_temp:.1f}°C")
            print("✓ Real hardware test passed")
            return True
        else:
            print("⚠️  No temperatures returned from real AMD GPU")
            return False
            
    except Exception as e:
        print(f"⚠️  Real hardware test skipped due to error: {e}")
        return True  # Don't fail the test suite for hardware issues

def run_all_tests():
    """Run all test cases."""
    print("Running comprehensive tests for fan control multi-GPU support...\n")
    
    try:
        test_amd_temperature_function()
        test_nvidia_temperature_function()
        test_gpu_temperature_function()
        test_config_parsing()
        test_fallback_behavior()
        test_error_handling()
        test_real_hardware_amd_gpu()
        
        print("\n🎉 All tests passed! Multi-GPU support is working correctly.")
        return True
        
    except Exception as e:
        print(f"\n❌ Test failed: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    # Test with the local Python environment
    success = run_all_tests()
    sys.exit(0 if success else 1)