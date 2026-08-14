"""麦克风采集测试：列出设备 + 读取 3 秒音量"""
import numpy as np
import sounddevice as sd

print("=== 输入设备列表 ===")
devices = sd.query_devices()
for i, d in enumerate(devices):
    if d['max_input_channels'] > 0:
        print(f"  [{i}] {d['name']}  (默认输入: {i == sd.default.device[0]})")

# 测试采集
print("\n=== 开始采集 3 秒（请对着麦克风说话）===")
sr = 44100
duration = 3.0
rec = sd.rec(int(sr * duration), samplerate=sr, channels=1, dtype='float32')
sd.wait()

# 分块计算音量
block = 2048
print("\n=== 音量采样（每块约 46ms）===")
for i in range(0, len(rec) - block, block):
    chunk = rec[i:i+block, 0]
    rms = np.sqrt(np.mean(chunk**2))
    if rms > 1e-10:
        db = 20 * np.log10(rms)
    else:
        db = -100
    # 映射 0-100: -60dB~-6dB -> 0~100
    vol = max(0, min(100, (db + 60) / 54 * 100))
    print(f"  RMS={rms:.5f}  dB={db:6.1f}  ->  音量 {vol:5.1f}")
print("\n采集完成。音量=0 说明没录到声音；音量波动说明正常。")
