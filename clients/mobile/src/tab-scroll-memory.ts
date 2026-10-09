type Visit = {
  id: number; key: string | null; target: number; pending: boolean;
  viewport: number; content: number; expected: number | null;
};

/** Session-only reading positions. A new visit retires all prior native callbacks. */
export class TabScrollMemory {
  private positions = new Map<string, number>();
  private sequence = 0;
  private current: Visit | null = null;

  begin(key: string | null): number {
    const id = ++this.sequence;
    this.current = {id, key, target: key ? this.positions.get(key) ?? 0 : 0,
      pending: key !== null, viewport: 0, content: 0, expected: null};
    return id;
  }

  end(id: number) {if (this.current?.id === id) this.current = null;}
  viewport(id: number, height: number) {
    if (this.current?.id === id && Number.isFinite(height)) this.current.viewport = Math.max(0, height);
  }
  content(id: number, height: number) {
    if (this.current?.id === id && Number.isFinite(height)) this.current.content = Math.max(0, height);
  }

  restore(id: number, allowClamping = false): number | null {
    const visit = this.current;
    if (!visit || visit.id !== id || !visit.pending || !visit.viewport || !visit.content) return null;
    const maximum = Math.max(0, visit.content - visit.viewport);
    // A freshly mounted async panel is often only a heading plus a spinner.
    if (!allowClamping && maximum + 1 < visit.target) return null;
    const offset = Math.min(visit.target, maximum);
    visit.pending = false;
    visit.expected = offset;
    this.remember(visit.key!, offset);
    return offset;
  }

  interact(id: number) {
    const visit = this.current;
    if (!visit || visit.id !== id) return;
    visit.pending = false; visit.expected = null;
  }

  record(id: number, offset: number) {
    const visit = this.current;
    if (!visit || visit.id !== id || !visit.key || visit.pending || !Number.isFinite(offset) || !visit.viewport || !visit.content) return;
    // iOS reports offsets outside the scrollable range while rubber-banding.
    // Saving one makes the next visit wait for content that can never exist.
    const y = Math.min(Math.max(0, offset), Math.max(0, visit.content - visit.viewport));
    // Ignore an initial zero-offset event queued before scrollTo was applied.
    if (visit.expected !== null && Math.abs(y - visit.expected) > 1) return;
    visit.expected = null;
    this.remember(visit.key, y);
  }

  private remember(key: string, offset: number) {
    this.positions.delete(key); this.positions.set(key, offset);
    if (this.positions.size > 32) this.positions.delete(this.positions.keys().next().value!);
  }
}
