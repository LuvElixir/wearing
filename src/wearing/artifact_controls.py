"""Portable, opt-in controls for standalone Wearing artifacts.

Copy these bytes into the artifact; no network or host application access.
Layout, data, calculations and business actions belong to the generated page.
"""

from pathlib import Path

CONTROL_CSS = (Path(__file__).with_name("web") / "result-controls.css").read_text(encoding="utf-8")

CONTROL_JS = """const WearingUI = (() => {
  function syncRange(input) {
    const host = input.closest('.wr-range');
    if (!host) return;
    const min = input.min === '' ? 0 : Number(input.min);
    const max = input.max === '' ? 100 : Number(input.max);
    const value = Number(input.value);
    const ratio = Number.isFinite(value) && max > min ? Math.min(1, Math.max(0, (value - min) / (max - min))) : 0;
    host.style.setProperty('--range-progress', String(ratio));
  }
  document.querySelectorAll('.wr-range input[type="range"]').forEach(input => {
    syncRange(input);
    input.addEventListener('input', () => syncRange(input));
  });
  return {syncRange};
})();"""

CONTROL_EXAMPLES = {
    "close": '<button type="button" class="wr-close" aria-label="关闭"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="m6 6 12 12M18 6 6 18"/></svg></button>',
    "disclosure": '<details class="wr-disclosure"><summary><svg class="wr-chevron" viewBox="0 0 20 20" aria-hidden="true"><path d="m7 4 6 6-6 6"/></svg><span>查看依据</span></summary><div>本次结果的真实依据。</div></details>',

    "number_field": '<div class="wr-field"><label for="amount">金额</label><input id="amount" type="number" inputmode="decimal" min="0" step="0.01" value="50" aria-describedby="amount-help"><span class="wr-field__unit">元</span></div><p id="amount-help">按本次问题说明单位、范围和错误状态。</p>',
    "range": '<label for="amount-range">调整金额</label><div class="wr-range"><div class="wr-range__rail" aria-hidden="true"><span class="wr-range__fill"></span></div><input id="amount-range" type="range" min="0" max="100" step="0.01" value="50"></div>',
}
