# Temperature Control Algorithm Analysis and Improvement Plan

## Current Algorithm Analysis

### Current Temperature Calculation (lines 305-312)
```python
cpu_temp_avg = round(sum(temps)/len(temps))
gpu_temps = get_gpu_temperatures()
if all(temp == 0 for temp in gpu_temps):
    print("Warning: All GPU temps reported as 0°C (check driver).", file=sys.stderr)
gpu_temp_avg = round(sum(gpu_temps)/len(gpu_temps))
gpu_temp_max = max(gpu_temps)
temp_eff = round((cpu_temp_avg + gpu_temp_max + gpu_temp_max + gpu_temp_avg) / 4)
if config['general']['debug']:
    print(f"[{host['name']}] CPU_Avg: {cpu_temp_avg} GPU_M: {gpu_temp_max} GPU_A: {gpu_temp_avg}")
max_temp_eff = max(temp_eff, cpu_temp_avg)
compute_fan_speed(max_temp_eff)
```

### Current Algorithm Issues

1. **Mixed CPU/GPU Weighting**: The current `temp_eff` formula gives equal weight to CPU average and GPU maximum, but then takes the maximum of `temp_eff` and `cpu_temp_avg`. This creates inconsistent behavior.

2. **No Separate Curves**: Both CPU and GPU temperatures use the same threshold curve, which may not be optimal since GPUs typically run hotter than CPUs.

3. **No Max Overpower Logic**: There's no special handling when maximum temperatures exceed thresholds significantly (e.g., by 15°C or more).

4. **Fixed Weighting**: The weighting between CPU and GPU is hardcoded (50/50) rather than configurable.

### Current Configuration
```yaml
temperatures:
  - 55    # 13% fan speed
  - 60    # 17% fan speed  
  - 70    # 25% fan speed
  - 75    # 37% fan speed
hysteresis: 2
```

## Proposed Improvements

### 1. Separate CPU and GPU Curves

**Rationale**: CPUs and GPUs have different thermal characteristics and operating ranges. GPUs typically run 10-20°C hotter than CPUs under load.

**Implementation**:
- Add separate temperature curves for CPU and GPU
- Allow different hysteresis values for each
- Maintain backward compatibility with single curve

### 2. Max Overpower Detection

**Rationale**: When any component exceeds its threshold by a significant margin (e.g., 15°C), that component should dominate the fan control decision.

**Implementation**:
- Add `max_overpower_threshold` parameter (default: 15°C)
- When max_temp > threshold + max_overpower_threshold, use max_temp directly
- Otherwise, use weighted average

### 3. Configurable Weighting

**Rationale**: Different systems may prioritize CPU vs GPU cooling differently.

**Implementation**:
- Add `cpu_weight` and `gpu_weight` parameters (default: 0.5 each)
- Allow dynamic adjustment based on workload detection

### 4. Improved Temperature Calculation

**New Algorithm**:
```python
def calculate_effective_temperature():
    cpu_temp_avg = round(sum(cpu_temps)/len(cpu_temps))
    gpu_temp_avg = round(sum(gpu_temps)/len(gpu_temps)) if gpu_temps else 0
    gpu_temp_max = max(gpu_temps) if gpu_temps else 0
    
    # Check for max overpower condition
    max_temp = max(cpu_temp_avg, gpu_temp_max)
    
    # Determine which curve to use based on which component is hotter
    if gpu_temp_max > cpu_temp_avg + 10:  # GPU significantly hotter
        effective_temp = gpu_temp_max
        use_gpu_curve = True
    elif cpu_temp_avg > gpu_temp_max + 10:  # CPU significantly hotter  
        effective_temp = cpu_temp_avg
        use_gpu_curve = False
    else:  # Balanced workload
        effective_temp = round(cpu_temp_avg * cpu_weight + gpu_temp_max * gpu_weight)
        use_gpu_curve = False  # Use CPU curve as default
    
    return effective_temp, use_gpu_curve
```

### 5. Proposed Configuration Structure

```yaml
temperature_control:
  # Global settings
  max_overpower_threshold: 15  # °C above threshold to trigger max-based control
  cpu_weight: 0.5           # Weight for CPU temperature (0.0-1.0)
  gpu_weight: 0.5           # Weight for GPU temperature (0.0-1.0)
  
  # CPU temperature curve (applies when CPU is dominant)
  cpu_curve:
    temperatures: [55, 60, 70, 75]
    speeds: [13, 17, 25, 37]
    hysteresis: 2
    
  # GPU temperature curve (applies when GPU is dominant)
  gpu_curve:
    temperatures: [65, 70, 80, 85]  # Higher thresholds for GPUs
    speeds: [15, 20, 30, 40]       # Slightly more aggressive cooling
    hysteresis: 3
```

### 6. Backward Compatibility

- If new configuration keys are missing, fall back to current behavior
- Single curve configuration automatically applies to both CPU and GPU
- Default weights maintain current 50/50 behavior

### 7. Implementation Steps

1. **Update Configuration Parsing**: Add support for new temperature_control structure
2. **Implement New Algorithm**: Replace current temp_eff calculation with improved logic
3. **Add Max Overpower Detection**: Implement threshold-based switching
4. **Update compute_fan_speed**: Support separate curves
5. **Add Debug Output**: Enhanced logging for troubleshooting
6. **Test and Validate**: Verify behavior with various scenarios

### 8. Expected Benefits

- **Better Cooling Efficiency**: Separate curves optimize cooling for each component type
- **Reduced Fan Noise**: More precise control reduces unnecessary fan speed increases
- **Improved Stability**: Max overpower detection prevents thermal runaway
- **Flexibility**: Configurable weights and curves adapt to different hardware
- **Maintainability**: Clearer algorithm logic is easier to understand and modify

### 9. Testing Scenarios

1. **CPU-Dominant Workload**: Verify CPU curve is used appropriately
2. **GPU-Dominant Workload**: Verify GPU curve is used when GPUs are hotter
3. **Balanced Workload**: Verify weighted average behavior
4. **Max Overpower Condition**: Verify immediate response to overheating
5. **Backward Compatibility**: Verify existing configurations still work
6. **Edge Cases**: Zero temperatures, missing sensors, etc.

### 10. Migration Path

1. Update fan_control.yaml with new structure (backward compatible)
2. Implement new algorithm with fallback to old behavior
3. Test with existing configurations
4. Gradually transition users to new configuration format
5. Deprecate old format in future versions

## Implementation Priority

1. **High Priority**: Max overpower detection (safety feature)
2. **High Priority**: Separate CPU/GPU curves (core improvement)
3. **Medium Priority**: Configurable weighting (flexibility)
4. **Low Priority**: Workload detection (future enhancement)

The proposed improvements will significantly enhance the fan control algorithm while maintaining full backward compatibility.