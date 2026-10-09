import type {ReactNode} from 'react';
import type {Connection, RecordItem} from './core';
import type {ReviewRequest} from './conversationLink';

export type ConversationProps = {
  connection: Connection;
  record?: RecordItem | null;
  active?: boolean;
  visible?: boolean;
  showComposer?: boolean;
  compactComposer?: boolean;
  inputScope?: string;
  reviewRequest?: ReviewRequest | null;
  content?: ReactNode;
  navigation?: ReactNode;
  onCapture?: () => void;
  onAdd?: () => void;
  onSend?: () => void;
  onOpenChat?: () => void;
  onArtifact?: (id: string) => void;
};
