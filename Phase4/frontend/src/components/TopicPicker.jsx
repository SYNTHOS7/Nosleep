import React from 'react'

/**
 * Topic scope picker component.
 * Allows filtering query scope to specific discovered topics or collection-wide.
 */
export default function TopicPicker({ topics, selectedTopicIds, onToggleTopic, onDiscoverTopics, isDiscovering }) {
  return (
    <div className="glass-card" id="topics-panel">
      <div className="card-title">
        <span>Thematic Scope</span>
        <button
          className="btn-primary"
          style={{ padding: '4px 10px', fontSize: '0.75rem' }}
          id="discover-topics-btn"
          onClick={onDiscoverTopics}
          disabled={isDiscovering}
        >
          {isDiscovering ? 'Clustering...' : 'Discover Themes'}
        </button>
      </div>

      <div className="topics-chip-list" id="topics-list">
        <div
          className={`topic-chip ${selectedTopicIds.length === 0 ? 'selected' : ''}`}
          id="topic-all"
          onClick={() => onToggleTopic('ALL')}
        >
          Collection-Wide (All)
        </div>

        {topics.map(t => {
          const isSelected = selectedTopicIds.includes(t.id)
          return (
            <div
              key={t.id}
              id={`topic-${t.id}`}
              className={`topic-chip ${isSelected ? 'selected' : ''}`}
              title={t.description}
              onClick={() => onToggleTopic(t.id)}
            >
              {t.label} ({t.chunk_count} chunks)
            </div>
          )
        })}
      </div>
    </div>
  )
}
