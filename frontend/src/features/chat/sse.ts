// Server-sent events read from a fetch response body. EventSource cannot send a POST with a
// JSON body and the CSRF header, so the chat endpoint is read this way instead.

export interface ServerEvent {
  event: string;
  data: unknown;
}

/** The events of ``body`` as they arrive; each ``data`` is parsed JSON. */
export async function* serverEvents(
  body: ReadableStream<Uint8Array>,
): AsyncGenerator<ServerEvent, void, undefined> {
  const reader = body.getReader();
  // One decoder for the whole stream, so a character cut between two reads is not lost.
  const decoder = new TextDecoder();
  let buffer = "";
  try {
    for (;;) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true }).replaceAll("\r\n", "\n");
      let end = buffer.indexOf("\n\n");
      while (end !== -1) {
        const parsed = parse(buffer.slice(0, end));
        if (parsed !== null) yield parsed;
        buffer = buffer.slice(end + 2);
        end = buffer.indexOf("\n\n");
      }
    }
    const last = parse(buffer);
    if (last !== null) yield last;
  } finally {
    reader.releaseLock();
  }
}

function parse(block: string): ServerEvent | null {
  let event = "message";
  const data: string[] = [];
  for (const line of block.split("\n")) {
    if (line.startsWith("event:")) event = line.slice(6).trim();
    else if (line.startsWith("data:")) data.push(line.slice(5).trimStart());
  }
  if (data.length === 0) return null;
  return { event, data: JSON.parse(data.join("\n")) as unknown };
}
