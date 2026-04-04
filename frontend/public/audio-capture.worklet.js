class NudiScribeCaptureProcessor extends AudioWorkletProcessor {
  process(inputs) {
    const input = inputs[0];
    if (!input || input.length === 0) {
      return true;
    }

    const channelCount = input.length;
    const frameCount = input[0].length;
    const mono = new Float32Array(frameCount);
    let energy = 0;

    for (let frameIndex = 0; frameIndex < frameCount; frameIndex += 1) {
      let sample = 0;
      for (let channelIndex = 0; channelIndex < channelCount; channelIndex += 1) {
        sample += input[channelIndex][frameIndex] || 0;
      }
      sample /= channelCount;
      mono[frameIndex] = sample;
      energy += sample * sample;
    }

    this.port.postMessage(
      {
        type: "audio",
        samples: mono,
        rms: Math.sqrt(energy / Math.max(frameCount, 1))
      },
      [mono.buffer]
    );

    return true;
  }
}

registerProcessor("nudiscribe-capture-processor", NudiScribeCaptureProcessor);
