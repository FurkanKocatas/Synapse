import { afterEach, describe, expect, it, vi } from "vitest";

import { fileKind } from "@/lib/fileKind";
import { source, sse } from "@/test/chat";
import { fakeApi } from "@/test/fakeApi";

import { answerParts, chatApi, passageRanges, plainAnswer } from "./chatApi";
import { markPassage } from "./PdfPage";
import { serverEvents } from "./sse";
import { advance, isRunning, started } from "./useLiveTurn";

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("chat pieces", () => {
  it("keeps a conversation ID from the address bar inside its own path segment", async () => {
    const calls = fakeApi(() => ({ status: 204 }));
    await chatApi.conversation("../admin/users");
    await chatApi.remove("k?x=1#y");
    expect(calls.map((call) => call.path)).toEqual([
      "/api/conversations/..%2Fadmin%2Fusers",
      "/api/conversations/k%3Fx%3D1%23y",
    ]);
  });

  it("reads server-sent events however the bytes are cut", async () => {
    const text = sse([
      ["turn", { conversation_id: "k", ordinal: 1 }],
      ["delta", { text: "çok satır\nve emoji 😀" }],
    ]);
    const bytes = new TextEncoder().encode(text);
    const body = new ReadableStream<Uint8Array>({
      start(controller) {
        for (let i = 0; i < bytes.length; i += 3) controller.enqueue(bytes.slice(i, i + 3));
        controller.close();
      },
    });
    const events = [];
    for await (const event of serverEvents(body)) events.push(event);
    expect(events).toEqual([
      { event: "turn", data: { conversation_id: "k", ordinal: 1 } },
      { event: "delta", data: { text: "çok satır\nve emoji 😀" } },
    ]);
  });

  it("takes the citations out of an answer", () => {
    expect(answerParts("Kurul 7 üyedir. [1] Başkan seçer. [2, 3]")).toEqual([
      { text: "Kurul 7 üyedir. " },
      { citations: [1] },
      { text: " Başkan seçer. " },
      { citations: [2, 3] },
    ]);
    expect(answerParts("[sic] metin")).toEqual([{ text: "[sic] metin" }]);
  });

  it("copies an answer without its citation markers", () => {
    expect(plainAnswer("Kurul 7 üyedir. [1] Başkan seçer. [2, 3]")).toBe(
      "Kurul 7 üyedir. Başkan seçer.",
    );
    expect(plainAnswer("Süre 10 yıldır [1].")).toBe("Süre 10 yıldır.");
  });

  it("tells a file's kind by its media type, or else by its name", () => {
    expect(fileKind("application/pdf", "karar")).toBe("pdf");
    expect(fileKind(null, "Rapor.DOCX")).toBe("doc");
    expect(fileKind("application/octet-stream", "kadro.xlsx")).toBe("sheet");
    expect(fileKind(null, "Meclis Kararı")).toBe("other");
  });

  it("finds a passage on its page whatever the spacing", () => {
    const pageText =
      "Başlık\n\nBelediye   meclisi\n7 üyeden oluşur. Kısa.\nBaşka bir paragraf burada.";
    const ranges = passageRanges(pageText, "Belediye meclisi 7 üyeden oluşur.\nKısa.");
    expect(ranges.map(([start, end]) => pageText.slice(start, end))).toEqual([
      "Belediye   meclisi\n7 üyeden oluşur.",
    ]);
    expect(passageRanges(pageText, "Burada olmayan bir cümle var.")).toEqual([]);
  });

  it("marks the cited passage in a PDF page's text layer", () => {
    const layer = document.createElement("div");
    layer.innerHTML =
      "<span>Giriş.</span><br><span>Belediye meclisi</span><span>7 üyeden oluşur.</span>" +
      "<span>Son.</span>";
    expect(markPassage(layer, "Belediye meclisi 7 üyeden oluşur.")).toBe(2);
    expect([...layer.querySelectorAll(".cited")].map((span) => span.textContent)).toEqual([
      "Belediye meclisi",
      "7 üyeden oluşur.",
    ]);
  });

  it("follows the events of a turn", () => {
    let turn = started("Soru?", null);
    expect(isRunning(turn)).toBe(true);
    turn = advance(turn, { event: "turn", data: { conversation_id: "k", ordinal: 2 } });
    turn = advance(turn, {
      event: "sources",
      data: { sources: [source], warnings: [], ranked: false },
    });
    expect(turn.ranked).toBe(false);
    turn = advance(turn, {
      event: "sources",
      data: { sources: [source], warnings: [], ranked: true },
    });
    expect(turn.ranked).toBe(true);
    turn = advance(turn, { event: "queued", data: { position: 2 } });
    expect(turn.queuePosition).toBe(2);
    turn = advance(turn, { event: "generating", data: {} });
    turn = advance(turn, { event: "delta", data: { text: "Kurul 9" } });
    turn = advance(turn, { event: "retrying", data: { unsupported: ["9"] } });
    expect(turn.retrying).toBe(true);
    expect(turn.text).toBe("");
    turn = advance(turn, { event: "rewritten", data: { question: "Kurul kaç üye?" } });
    turn = advance(turn, {
      event: "answer",
      data: {
        status: "answered",
        text: "Kurul 7. [1]",
        citations: [1],
        error: null,
        stripped: 0,
        kind: "documents",
      },
    });
    expect([turn.conversationId, turn.ordinal]).toEqual(["k", 2]);
    expect(turn.rewritten).toBe("Kurul kaç üye?");
    expect(isRunning(turn)).toBe(false);
    expect(isRunning(advance(started("x", null), { event: "error", data: { error: "x" } }))).toBe(
      false,
    );
  });
});
