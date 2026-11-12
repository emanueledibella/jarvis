// A word match avoids activating on names such as "Jarvison". Unicode token
// boundaries also handle punctuation, multiword phrases and non-Latin text.
export function afterWake(text: string, phrase: string): string | null {
  const words = [...text.matchAll(/[\p{L}\p{N}]+/gu)];
  const wanted = [
    ...phrase.toLocaleLowerCase().matchAll(/[\p{L}\p{N}]+/gu),
  ].map((value) => value[0]);
  if (!wanted.length) return null;
  for (let index = 0; index <= words.length - wanted.length; index++) {
    if (
      wanted.every(
        (word, offset) => words[index + offset][0].toLocaleLowerCase() === word,
      )
    ) {
      const last = words[index + wanted.length - 1];
      return text
        .slice(last.index! + last[0].length)
        .replace(/^[\s\p{P}]+/u, "")
        .trim();
    }
  }
  return null;
}

export function voicePreferenceKey(server: string, device: string) {
  return "jarvis-companion-voice:" + server + ":" + device;
}

export function canContinueVoice(
  started: { session: string; revision: number },
  session: string,
  revision: number,
) {
  return started.session === session && started.revision === revision;
}

// Preserve the fractional input position between chunks, including the last
// sample, so 44.1/48 kHz microphones do not accumulate gaps at 24 kHz.
export class PCMResampler {
  private samples = new Float32Array(0);
  private position = 0;
  private inputRate: number;
  private outputRate: number;
  constructor(inputRate: number, outputRate = 24000) {
    this.inputRate = inputRate;
    this.outputRate = outputRate;
  }
  push(chunk: Float32Array): Int16Array {
    const data = new Float32Array(this.samples.length + chunk.length);
    data.set(this.samples);
    data.set(chunk, this.samples.length);
    const step = this.inputRate / this.outputRate;
    const output: number[] = [];
    while (this.position + 1 < data.length) {
      const base = Math.floor(this.position),
        fraction = this.position - base;
      const sample = Math.max(
        -1,
        Math.min(1, data[base] * (1 - fraction) + data[base + 1] * fraction),
      );
      output.push(Math.round(sample * (sample < 0 ? 32768 : 32767)));
      this.position += step;
    }
    const used = Math.min(Math.floor(this.position), data.length);
    this.samples = data.slice(used);
    this.position -= used;
    return Int16Array.from(output);
  }
}
