/** A dev runtime alone must not expose custom services in an ordinary build. */
export function developmentConnectionsEnabled(): boolean {
  return typeof __DEV__ !== 'undefined' && __DEV__ === true && process.env.EXPO_PUBLIC_ALLOW_DEVELOPMENT_CONNECTIONS === 'true';
}
