import {useEffect} from 'react';
import {Platform} from 'react-native';
import {colors} from './tokens';

/** Applies to RN Web modals too; native focus remains owned by the OS. */
export function ExperienceFocus() {
  useEffect(() => {
    if (Platform.OS !== 'web') return;
    const root = document.documentElement;
    root.setAttribute('data-wearing-experience', '');
    const style = document.createElement('style');
    style.textContent = `
      html[data-wearing-experience] :is(button,input,textarea,[tabindex],[role="button"],[role="tab"],[role="checkbox"]):focus {outline:none!important;}
      html[data-wearing-experience] :is(button,[role="button"],[role="tab"],[role="checkbox"]):focus-visible {box-shadow:inset 0 0 0 1.5px ${colors.muted};}
      html[data-wearing-experience] :is(input,textarea):focus {outline:0!important;box-shadow:inset 0 0 0 1px ${colors.accent}66;}
      html[data-wearing-experience] :is(input,textarea)[data-testid="intent-text"]:focus {box-shadow:none!important;}
      html[data-wearing-experience] :is(button,input,textarea,[role="button"],[role="tab"]) {-webkit-tap-highlight-color:transparent;transition:box-shadow 140ms ease,background-color 140ms ease;}
      @media(prefers-reduced-motion:reduce) {html[data-wearing-experience] * {transition-duration:0ms!important;}}
    `;
    document.head.appendChild(style);
    return () => {style.remove();root.removeAttribute('data-wearing-experience');};
  }, []);
  return null;
}
