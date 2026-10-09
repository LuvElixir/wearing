/** Continuous area resampling, so native callback boundaries cannot duplicate or lose samples. */
export class VoicePcm {
  private rate = 0;
  private weight = 0;
  private sum = 0;
  push(buffer: ArrayBuffer, rate: number, channels: number): Uint8Array {
    if (![16000, 24000, 32000, 44100, 48000].includes(rate) || channels !== 1 ||
        !buffer.byteLength || buffer.byteLength % 4 || buffer.byteLength > rate * 4 || (this.rate && this.rate !== rate)) throw new Error('Unsupported microphone format');
    this.rate = rate;
    const source = new Float32Array(buffer);
    const ratio = rate / 16000;
    const values: number[] = [];
    for (const sample of source) {
      if (!Number.isFinite(sample) || Math.abs(sample) > 1.01) throw new Error('Invalid microphone samples');
      let remaining = 1;
      while (remaining > 1e-8) {
        const used = Math.min(remaining, ratio - this.weight);
        this.sum += sample * used; this.weight += used; remaining -= used;
        if (this.weight >= ratio - 1e-8) {
          const value = Math.max(-1, Math.min(1, this.sum / ratio));
          values.push(Math.round(value * (value < 0 ? 32768 : 32767)));
          this.sum = 0; this.weight = 0;
        }
      }
    }
    const bytes = new Uint8Array(values.length * 2), view = new DataView(bytes.buffer);
    values.forEach((value, index) => view.setInt16(index * 2, value, true));
    return bytes;
  }
}

export function wavHeader(bytes: number): Uint8Array {
  const header = new Uint8Array(44), view = new DataView(header.buffer);
  const word = (offset: number, value: string) => [...value].forEach((c, i) => view.setUint8(offset + i, c.charCodeAt(0)));
  word(0, 'RIFF'); view.setUint32(4, 36 + bytes, true); word(8, 'WAVE'); word(12, 'fmt ');
  view.setUint32(16, 16, true); view.setUint16(20, 1, true); view.setUint16(22, 1, true);
  view.setUint32(24, 16000, true); view.setUint32(28, 32000, true); view.setUint16(32, 2, true); view.setUint16(34, 16, true);
  word(36, 'data'); view.setUint32(40, bytes, true);
  return header;
}
