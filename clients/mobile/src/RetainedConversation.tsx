import Conversation from './Conversation';
import type {ConversationProps} from './conversation-props';

// The parent scopes this instance to one identity. Keep its WebView and input
// mounted across tabs; visibility changes only the content above the input.
export default function RetainedConversation(props: ConversationProps) {
  return <Conversation {...props}/>;
}
