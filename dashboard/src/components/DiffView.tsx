function lineClass(line: string): string {
  if (line.startsWith("+++") || line.startsWith("---") || line.startsWith("diff ") || line.startsWith("index ")) return "meta";
  if (line.startsWith("@@")) return "hunk";
  if (line.startsWith("+")) return "add";
  if (line.startsWith("-")) return "del";
  return "";
}

export function DiffView({ diff }: { diff: string }) {
  if (!diff.trim()) return <p className="muted">No diff recorded.</p>;
  return (
    <pre className="diff" tabIndex={0}>
      {diff.replace(/\n$/, "").split("\n").map((line, i) => (
        <span key={i} className={lineClass(line)}>{line || " "}{"\n"}</span>
      ))}
    </pre>
  );
}
