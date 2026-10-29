import React from 'react'

const span = value => value ? `${value[0]}–${value[1]}` : 'none'

export default function ChangeImpact({ impact }) {
  if (!impact) return null
  if (!impact.available) return <p>{impact.reason}</p>
  return <section className="repo-architecture" aria-label="Code change impact">
    <h3>What could this change affect?</h3>
    <p>{impact.changed_files.length} changed files · {impact.affected_count} potentially affected importing files · {impact.findings_to_review.length} finding candidates to inspect.</p>
    <p>These are review targets, not confirmed new bugs or required code edits. Line numbers refer to the indicated snapshot.</p>
    {!impact.dependency_mapping_available && <p>One or both older scans lack an architecture map. Rescan both versions for dependency impact.</p>}
    <h4>Changed files and lines</h4>
    {impact.changed_files.length === 0 && <p>No supported source-file content changes detected.</p>}
    <ul>{impact.changed_files.slice(0, 100).map(file => <li key={file.file}>
      <strong>{file.file}</strong> · {file.status}
      {file.line_ranges_available ? <ul>{file.changed_ranges.map((range, i) => <li key={i}>{range.operation}: before lines {span(range.before)} → after lines {span(range.after)}</li>)}</ul> : <p>Line comparison unavailable for this file. Rescan both versions or inspect the source diff.</p>}
      {file.ranges_omitted && <p>Additional changed ranges omitted by the output limit.</p>}
    </li>)}</ul>
    {impact.changed_files.length > 100 && <p>First 100 changed files shown.</p>}
    <details open={impact.affected_count > 0}><summary>Import locations to inspect ({impact.affected_count})</summary>
      <div>{impact.potentially_affected.map(item => <details key={item.file}>
        <summary>{item.file} · {item.depth === 1 ? 'Direct connection' : 'Indirect connection'}</summary>
        <p>{item.reason}: {item.changed_dependency}</p>
        <ul>{item.evidence_chain.map((edge, i) => <li key={i}>{edge.source} imports {edge.target} · {edge.evidence.file}:{edge.evidence.line} ({edge.snapshot} snapshot)</li>)}</ul>
        <p>{item.action}</p>
      </details>)}</div>
      {impact.affected_list_truncated && <p>First 200 potentially affected files shown.</p>}
      {!impact.affected_count && <p>No importing files found within the static map. Dynamic or external consumers may still be affected.</p>}
    </details>
    <h4>Possible problems to investigate</h4>
    {impact.findings_to_review.length ? <ul>{impact.findings_to_review.map(finding => <li key={finding.id}>{finding.title} · {finding.file}:{finding.line} (after snapshot). {finding.fix}</li>)}</ul> : <p>No matching finding candidates in changed or potentially affected files. General logic bugs are not ruled out.</p>}
    <details><summary>Routes and tests to revisit</summary>
      <p>{impact.route_count} route declaration candidates in changed or importing files. First 100 shown.</p>
      <ul>{impact.route_candidates_to_retest.map(route => <li key={route.id}>{route.method} · {route.function} · {route.file}:{route.line} (after snapshot)</li>)}</ul>
      <p>Connected test files: {impact.connected_test_files.join(', ') || 'None identified from imports. Choose and run tests manually.'}</p>
    </details>
    <details><summary>How to use this review</summary><ul>{impact.guidance.map(text => <li key={text}>{text}</li>)}</ul><p>{impact.limitations}</p></details>
  </section>
}
