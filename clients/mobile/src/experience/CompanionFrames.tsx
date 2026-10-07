import type {RefObject} from 'react';
import type {View} from 'react-native';

export type CompanionFramesProps = {host: RefObject<View | null>; playing: boolean; testID: string; onFrame: () => void; onFailure: () => void};

// Native keeps Expo Video's native rendering surface.
export function CompanionFrames(_props: CompanionFramesProps) {return null;}
