import type { ConversationSummary } from "../types/api";


interface ConversationSidebarProps {
  activeConversationId: string | undefined;
  conversations: ConversationSummary[];
  loading: boolean;
  onCreate: () => void;
  onDelete: (conversation: ConversationSummary) => void;
  onOpen: (conversation: ConversationSummary) => void;
  onRename: (conversation: ConversationSummary) => void;
}

export function ConversationSidebar({
  activeConversationId,
  conversations,
  loading,
  onCreate,
  onDelete,
  onOpen,
  onRename,
}: ConversationSidebarProps) {
  return (
    <aside className="conversation-sidebar" aria-label="Conversation history">
      <div className="conversation-sidebar-header">
        <div>
          <span className="eyebrow">History</span>
          <h2>Conversations</h2>
        </div>
        <button className="button button-secondary conversation-new" onClick={onCreate} type="button">
          + New chat
        </button>
      </div>
      {loading ? (
        <p className="panel-empty" role="status">Loading conversations…</p>
      ) : conversations.length === 0 ? (
        <div className="conversation-empty">
          <strong>No conversations yet</strong>
          <span>Start a chat and it will stay here for next time.</span>
        </div>
      ) : (
        <ul className="conversation-list">
          {conversations.map((conversation) => (
            <li
              className={conversation.id === activeConversationId ? "is-active" : undefined}
              key={conversation.id}
            >
              <button
                aria-label={`Open ${conversation.title}`}
                className="conversation-open"
                onClick={() => onOpen(conversation)}
                type="button"
              >
                <strong>{conversation.title}</strong>
                <span>{conversation.messageCount} messages</span>
              </button>
              <div className="conversation-actions">
                <button
                  aria-label={`Rename ${conversation.title}`}
                  className="text-button"
                  onClick={() => onRename(conversation)}
                  type="button"
                >
                  Rename
                </button>
                <button
                  aria-label={`Delete ${conversation.title}`}
                  className="text-button danger-text"
                  onClick={() => onDelete(conversation)}
                  type="button"
                >
                  Delete
                </button>
              </div>
            </li>
          ))}
        </ul>
      )}
    </aside>
  );
}
