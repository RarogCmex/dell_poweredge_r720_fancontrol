#!/usr/bin/env python3

"""
Test suite for the improved temperature control algorithm.
Tests the new calculate_effective_temperature and compute_fan_speed functions.
"""

import sys
import os
sys.path.insert(0, '.')

# Mock the sensors module for testing
class MockSensor:
    def __init__(self, prefix):
        self.prefix = prefix
        
    def get_features(self):
        return []
    
    def get_all_subfeatures(self, feature):
        return []
    
    def get_value(self, number):
        return 45  # Mock CPU temperature

class MockSensors:
    @staticmethod
    def get_detected_chips():
        return [MockSensor("coretemp")]
    
    @staticmethod
    def cleanup():
        pass

# Mock sensors module
sys.modules['sensors'] = MockSensors()

import fan_control

def test_cpu_dominant():
    """Test CPU dominant scenario"""
    print("Testing CPU dominant scenario...")
    
    fan_control.config = {
        'general': {'debug': False},
        'host': {
            'name': 'Test',
            'temperatures': [55, 60, 70, 75],
            'speeds': [13, 17, 25, 37],
            'hysteresis': 2
        },
        'temperature_control': {
            'max_overpower_threshold': 15,
            'cpu_weight': 0.5,
            'gpu_weight': 0.5,
            'cpu_curve': {
                'temperatures': [55, 60, 70, 75],
                'speeds': [13, 17, 25, 37],
                'hysteresis': 2
            },
            'gpu_curve': {
                'temperatures': [65, 70, 80, 85],
                'speeds': [15, 20, 30, 40],
                'hysteresis': 3
            }
        }
    }
    
    cpu_temp = 80
    gpu_temps = [55, 52, 50]
    
    effective_temp, use_gpu_curve, debug_info = fan_control.calculate_effective_temperature(cpu_temp, gpu_temps)
    
    assert effective_temp == 80, f"Expected 80°C, got {effective_temp}°C"
    assert use_gpu_curve == False, f"Expected CPU curve, got GPU curve"
    assert debug_info['decision'] == 'cpu_dominant', f"Expected cpu_dominant, got {debug_info['decision']}"
    
    print("✓ CPU dominant test passed")

def test_gpu_dominant():
    """Test GPU dominant scenario"""
    print("Testing GPU dominant scenario...")
    
    fan_control.config = {
        'general': {'debug': False},
        'host': {
            'name': 'Test',
            'temperatures': [55, 60, 70, 75],
            'speeds': [13, 17, 25, 37],
            'hysteresis': 2
        },
        'temperature_control': {
            'max_overpower_threshold': 15,
            'cpu_weight': 0.5,
            'gpu_weight': 0.5,
            'cpu_curve': {
                'temperatures': [55, 60, 70, 75],
                'speeds': [13, 17, 25, 37],
                'hysteresis': 2
            },
            'gpu_curve': {
                'temperatures': [65, 70, 80, 85],
                'speeds': [15, 20, 30, 40],
                'hysteresis': 3
            }
        }
    }
    
    cpu_temp = 60
    gpu_temps = [75, 72, 70]
    
    effective_temp, use_gpu_curve, debug_info = fan_control.calculate_effective_temperature(cpu_temp, gpu_temps)
    
    assert effective_temp == 75, f"Expected 75°C, got {effective_temp}°C"
    assert use_gpu_curve == True, f"Expected GPU curve, got CPU curve"
    assert debug_info['decision'] == 'gpu_dominant', f"Expected gpu_dominant, got {debug_info['decision']}"
    
    print("✓ GPU dominant test passed")

def test_balanced_workload():
    """Test balanced workload scenario"""
    print("Testing balanced workload scenario...")
    
    fan_control.config = {
        'general': {'debug': False},
        'host': {
            'name': 'Test',
            'temperatures': [55, 60, 70, 75],
            'speeds': [13, 17, 25, 37],
            'hysteresis': 2
        },
        'temperature_control': {
            'max_overpower_threshold': 15,
            'cpu_weight': 0.5,
            'gpu_weight': 0.5,
            'cpu_curve': {
                'temperatures': [55, 60, 70, 75],
                'speeds': [13, 17, 25, 37],
                'hysteresis': 2
            },
            'gpu_curve': {
                'temperatures': [65, 70, 80, 85],
                'speeds': [15, 20, 30, 40],
                'hysteresis': 3
            }
        }
    }
    
    cpu_temp = 65
    gpu_temps = [68, 66, 64]
    
    effective_temp, use_gpu_curve, debug_info = fan_control.calculate_effective_temperature(cpu_temp, gpu_temps)
    
    expected_temp = round(65 * 0.5 + 68 * 0.5)  # 66.5 -> 67
    assert effective_temp == expected_temp, f"Expected {expected_temp}°C, got {effective_temp}°C"
    assert use_gpu_curve == False, f"Expected CPU curve for balanced, got GPU curve"
    assert debug_info['decision'] == 'balanced', f"Expected balanced, got {debug_info['decision']}"
    
    print("✓ Balanced workload test passed")

def test_no_gpus():
    """Test scenario with no GPUs"""
    print("Testing no GPUs scenario...")
    
    fan_control.config = {
        'general': {'debug': False},
        'host': {
            'name': 'Test',
            'temperatures': [55, 60, 70, 75],
            'speeds': [13, 17, 25, 37],
            'hysteresis': 2
        },
        'temperature_control': {
            'max_overpower_threshold': 15,
            'cpu_weight': 0.5,
            'gpu_weight': 0.5,
            'cpu_curve': {
                'temperatures': [55, 60, 70, 75],
                'speeds': [13, 17, 25, 37],
                'hysteresis': 2
            },
            'gpu_curve': {
                'temperatures': [65, 70, 80, 85],
                'speeds': [15, 20, 30, 40],
                'hysteresis': 3
            }
        }
    }
    
    cpu_temp = 65
    gpu_temps = []
    
    effective_temp, use_gpu_curve, debug_info = fan_control.calculate_effective_temperature(cpu_temp, gpu_temps)
    
    assert effective_temp == 65, f"Expected 65°C, got {effective_temp}°C"
    assert use_gpu_curve == False, f"Expected CPU curve, got GPU curve"
    
    print("✓ No GPUs test passed")

def test_backward_compatibility():
    """Test backward compatibility with old config format"""
    print("Testing backward compatibility...")
    
    fan_control.config = {
        'general': {'debug': False},
        'host': {
            'name': 'Test',
            'temperatures': [55, 60, 70, 75],
            'speeds': [13, 17, 25, 37],
            'hysteresis': 2
        }
        # No temperature_control section - should use defaults
    }
    
    cpu_temp = 65
    gpu_temps = [70, 68, 66]
    
    # Should not raise any errors and use default values
    effective_temp, use_gpu_curve, debug_info = fan_control.calculate_effective_temperature(cpu_temp, gpu_temps)
    
    # With default weights (0.5 each), should get weighted average
    expected_temp = round(65 * 0.5 + 70 * 0.5)  # 67.5 -> 68
    assert effective_temp == expected_temp, f"Expected {expected_temp}°C, got {effective_temp}°C"
    
    print("✓ Backward compatibility test passed")

def test_custom_weights():
    """Test custom weighting"""
    print("Testing custom weights...")
    
    fan_control.config = {
        'general': {'debug': False},
        'host': {
            'name': 'Test',
            'temperatures': [55, 60, 70, 75],
            'speeds': [13, 17, 25, 37],
            'hysteresis': 2
        },
        'temperature_control': {
            'max_overpower_threshold': 15,
            'cpu_weight': 0.7,  # CPU weighted more
            'gpu_weight': 0.3,  # GPU weighted less
            'cpu_curve': {
                'temperatures': [55, 60, 70, 75],
                'speeds': [13, 17, 25, 37],
                'hysteresis': 2
            },
            'gpu_curve': {
                'temperatures': [65, 70, 80, 85],
                'speeds': [15, 20, 30, 40],
                'hysteresis': 3
            }
        }
    }
    
    # Test CPU dominant scenario
    cpu_temp = 80
    gpu_temps = [65, 63, 61]  # 15°C difference, CPU is hotter
    
    effective_temp, use_gpu_curve, debug_info = fan_control.calculate_effective_temperature(cpu_temp, gpu_temps)
    
    # Should be CPU dominant due to >10°C difference (CPU hotter)
    assert effective_temp == 80, f"Expected 80°C (CPU dominant), got {effective_temp}°C"
    assert use_gpu_curve == False, f"Expected CPU curve, got GPU curve"
    assert debug_info['decision'] == 'cpu_dominant', f"Expected cpu_dominant, got {debug_info['decision']}"
    
    print("✓ Custom weights test passed")

def run_all_tests():
    """Run all tests"""
    print("Running temperature algorithm tests...\n")
    
    try:
        test_cpu_dominant()
        test_gpu_dominant()
        test_balanced_workload()
        test_no_gpus()
        test_backward_compatibility()
        test_custom_weights()
        
        print("\n🎉 All tests passed! The improved temperature algorithm is working correctly.")
        return True
        
    except Exception as e:
        print(f"\n❌ Test failed: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    success = run_all_tests()
    sys.exit(0 if success else 1)