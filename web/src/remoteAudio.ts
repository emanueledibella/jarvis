export function encodePCM16(samples: Float32Array, sampleRate = 16000): ArrayBuffer {
  if (!samples.length || samples.length > sampleRate * 60) throw new Error("Record at most one minute.");
  const buffer = new ArrayBuffer(44 + samples.length * 2), view = new DataView(buffer);
  const ascii = (offset: number, text: string) => { for (let i = 0; i < text.length; i++) view.setUint8(offset + i, text.charCodeAt(i)); };
  ascii(0, "RIFF"); view.setUint32(4, buffer.byteLength - 8, true); ascii(8, "WAVE"); ascii(12, "fmt ");
  view.setUint32(16, 16, true); view.setUint16(20, 1, true); view.setUint16(22, 1, true);
  view.setUint32(24, sampleRate, true); view.setUint32(28, sampleRate * 2, true); view.setUint16(32, 2, true); view.setUint16(34, 16, true);
  ascii(36, "data"); view.setUint32(40, samples.length * 2, true);
  for (let i = 0; i < samples.length; i++) { const s = Math.max(-1, Math.min(1, Number.isFinite(samples[i]) ? samples[i] : 0)); view.setInt16(44 + i * 2, s < 0 ? s * 32768 : s * 32767, true); }
  return buffer;
}

export async function canonicalAudio(payload: { content: string; mime: string; seconds: number }) {
  const bytes = Uint8Array.from(atob(payload.content), character => character.charCodeAt(0));
  if (bytes.byteLength > 3_000_000) throw new Error("Recording exceeds its size limit.");
  const context = new AudioContext();
  try {
    const decoded = await context.decodeAudioData(bytes.buffer);
    if (decoded.duration > 60.1 || decoded.duration < .1) throw new Error("Record between 0.1 and 60 seconds.");
    const length = Math.min(960000, Math.ceil(decoded.duration * 16000));
    const offline = new OfflineAudioContext(1, length, 16000);
    const source = offline.createBufferSource(); source.buffer = decoded; source.connect(offline.destination); source.start();
    const result = await offline.startRendering();
    const wav = new Uint8Array(encodePCM16(result.getChannelData(0)));
    let binary = ""; for (let offset = 0; offset < wav.length; offset += 8192) binary += String.fromCharCode(...wav.subarray(offset, offset + 8192));
    return { content: btoa(binary), mime: "audio/wav", seconds: length / 16000 };
  } finally { await context.close(); }
}
