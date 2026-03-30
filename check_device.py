import pyaudio

p = pyaudio.PyAudio()
print("可用音訊設備:")
for i in range(p.get_device_count()):
    dev = p.get_device_info_by_index(i)
    print(f"設備編號 {i}: {dev['name']} (Max Input Channels: {dev['maxInputChannels']})")