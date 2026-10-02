"""What the chat says when it does not answer from the documents (docs/design/answers.md):
a greeting answered in conversation, a message the search found nothing for judged by the
model (the route), an answer from general knowledge, a classic conversation; and when it is,
for the model, which does not know the day.
"""

import re
from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from synapse.knowledge.public import Overview, lower

# Answers that rest on no document: a reply in conversation, or one from general knowledge.
CONVERSATION_SYSTEM = (
    "Sen Synapse'sin: bir kurumun belgelerinden, kaynağını göstererek soru cevaplayan bir "
    "asistan. Şu an belgelerden değil, sohbet olarak cevap veriyorsun. Kısa, sıcak ve doğal "
    "yaz; mesajın dilinde cevap ver. Kurumun belgeleri, kararları, bütçesi, kişileri ya da "
    "sayıları hakkında hiçbir bilgi uydurma; böyle bir şey sorulursa bunu belgelerde "
    "arayabileceğini söyle. Ne yapabildiğin sorulursa: kurumun belgelerinde arama yapıp "
    "cevabı kaynağıyla verebildiğini, belgeleri yükleyip düzenlemeye yardım ettiğini ve genel "
    "sorularda da yardımcı olabildiğini anlat; erişebildiği belgeler sorulursa aşağıdaki "
    "özeti kullan. {library} {when}"
)
# A question about the collection itself ("belgelerde neler var", "kaç belge var"): answered
# from what the documents are (knowledge/library.py), not from a search of their text.
LIBRARY_SYSTEM = (
    "Sen Synapse'sin: bir kurumun belgelerinden, kaynağını göstererek soru cevaplayan bir "
    "asistan. Kullanıcı belge arşivinin kendisini soruyor: neler var, kaç belge var, hangi "
    "klasörler var, ne tür belgeler var, en son ne eklendi. Aşağıdaki listeye dayanarak, "
    "mesajın dilinde, derli toplu ve doğal cevap ver: sayıları listeden al; belgelerin "
    "konularını adlarından ve ilk satırlarından çıkarıp gruplayarak özetle; listede olmayan "
    "bir belgeden söz etme. Bir belgenin içeriği ayrıntılı sorulursa, soruyu doğrudan "
    "sormasını öner: o zaman belgelerde arar ve kaynağıyla cevaplarsın.\n\n{library}\n\n{when}"
)
LIBRARY_TOKENS = 900
# How much of the conversation an answer without documents sees: enough to follow a chat.
TALK_TURNS = 6
TALK_CHARS = 2000
_MEDIA = {
    "application/pdf": "PDF",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": "Word",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": "Excel",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation": "PowerPoint",
}
GENERAL_SYSTEM = (
    "Sen Synapse'sin: bir kurumun belgelerinden, kaynağını göstererek soru cevaplayan bir "
    "asistan. Bu mesaj kurumun belgeleriyle ilgili değil; genel bilginle ya da istenen yazma, "
    "özetleme, çeviri yardımıyla, mesajın dilinde, doğru ve derli toplu cevap ver. Emin "
    "olmadığın şeyi kesin gibi yazma. Kurum hakkında hiçbir bilgi uydurma. {when}"
)
# A classic conversation: the user's own conversation with the model, with no rule of ours but
# the date (the model does not know it).
CLASSIC_SYSTEM = "Sen yardımsever bir asistansın. Kullanıcının yazdığı dilde cevap ver. {when}"
CLASSIC_TURNS = 10
CLASSIC_CHARS = 4000
CLASSIC_TOKENS = 1500
MONTHS = (
    "Ocak",
    "Şubat",
    "Mart",
    "Nisan",
    "Mayıs",
    "Haziran",
    "Temmuz",
    "Ağustos",
    "Eylül",
    "Ekim",
    "Kasım",
    "Aralık",
)
DAYS = ("Pazartesi", "Salı", "Çarşamba", "Perşembe", "Cuma", "Cumartesi", "Pazar")


def moment(now: datetime | None) -> str:
    """When it is, as the user's clock says (``now``, sent by the page), else the server's."""
    now = now or datetime.now().astimezone()
    return (
        f"Şu an {now.day} {MONTHS[now.month - 1]} {now.year} {DAYS[now.weekday()]}, "
        f"saat {now:%H:%M}."
    )


def summary(library: Overview | None) -> str:
    """The collection in a sentence, for replies in conversation."""
    if library is None:
        return ""
    folders = ", ".join(f"{f.path} ({f.documents})" for f in library.folders[:12])
    return (
        f"Kullanıcının erişebildiği belgeler: {library.total} belge, {len(library.folders)} "
        f"klasörde ({folders})."
    )


def describe(library: Overview | None) -> str:
    """The collection as the model reads it: the counts, the folders, the newest documents."""
    if library is None or library.total == 0:
        return "Kullanıcının erişebildiği hiçbir belge yok."
    lines = [
        f"Kullanıcının erişebildiği belgeler: toplam {library.total} ({library.ready} hazır, "
        f"{library.working} hazırlanıyor, {library.failed} okunamadı).",
        "Klasörler:",
        *(f"- {f.path}: {f.documents} belge" for f in library.folders),
        f"En yeni {len(library.newest)} belge (en yeni önce; ad | klasör | tür | eklendiği gün "
        "| ilk satırları):",
    ]
    for d in library.newest:
        kind = _MEDIA.get(d.media_type, "görsel" if d.media_type.startswith("image/") else "dosya")
        size = f"{kind}, {d.pages} sayfa" if d.pages else kind
        added = f"{d.added.day} {MONTHS[d.added.month - 1]} {d.added.year}"
        lines.append(f"- {d.title} | {d.folder} | {size} | {added} | {d.opening}")
    if library.total > len(library.newest):
        lines.append(f"(Listede yalnızca en yeni {len(library.newest)} belge var.)")
    return "\n".join(lines)


ROUTE_SYSTEM = (
    "Bir kurumun belge asistanına gelen son mesajın türünü seç. 'conversation': selamlaşma, "
    "teşekkür, vedalaşma, asistanın kendisine dair bir soru (kim olduğu, ne yapabildiği) ya da "
    "bilgi istemeyen sohbet. 'general': kurumla ilgisi olmayan, genel bilgiyle cevaplanan bir "
    "soru (bir kavramın tanımı, bir hesaplama, bir programlama sorusu) ya da metin yazma, "
    "özetleme, çeviri isteği. 'documents': kurumun kendisi, birimleri, belgeleri, kararları, "
    "bütçesi, personeli, mevzuatı, tarihleri, sayıları ya da işleyişi hakkında her soru. Emin "
    "değilsen 'documents' seç."
)
# The route has no 'library': offered one (eval/answers/route.py, 2026-10-03), it caught 3 of 6
# questions about the collection and sent an unanswerable one ("metformin başlangıç dozu") to
# general knowledge. Questions about the collection are recognised by about_library alone.
ROUTE_SCHEMA = {
    "type": "object",
    "properties": {"kind": {"type": "string", "enum": ["conversation", "general", "documents"]}},
    "required": ["kind"],
}
ROUTE_TOKENS = 16
REPLY_TOKENS = 700

type Talk = Literal["conversation", "general", "library"]


@dataclass(frozen=True)
class Voice:
    """How an answer without documents is asked for: its system prompt, how much of the
    conversation the model sees, and how long the answer may be."""

    system: str
    turns: int = TALK_TURNS
    chars: int = TALK_CHARS
    max_tokens: int = REPLY_TOKENS


def voice_for(kind: Talk, library: Overview | None, when: str) -> Voice:
    """The voice of each answer without documents; the collection in it where it helps."""
    if kind == "general":
        return Voice(GENERAL_SYSTEM.format(when=when))
    if kind == "library":
        system = LIBRARY_SYSTEM.format(library=describe(library), when=when)
        return Voice(system, max_tokens=LIBRARY_TOKENS)
    return Voice(CONVERSATION_SYSTEM.format(library=summary(library), when=when))


# A greeting, thanks or farewell, alone or two or three together ("selam, nasılsın"), with an
# address at most ("hocam"). The whole message must be that: "merhaba, bütçe ne kadar?" is a
# question and is searched.
_PHRASES = (
    r"selam(?:lar)?|slm|merhaba(?:lar)?|mrb|hey|hi|hello|g[uü]nayd[iı]n|"
    r"iyi (?:g[uü]nler|ak[sş]amlar|geceler|sabahlar|[cç]al[iı][sş]malar)|"
    r"nas[iı]ls[iı]n(?:[iı]z)?|naber|ne haber|kolay gelsin|"
    r"(?:[cç]ok )?te[sş]ekk[uü]r(?:ler| ederim| ederiz)?|sa[gğ] ?ol(?:un)?|eyvallah|"
    r"tamam(?:d[iı]r)?|peki|anlad[iı]m|harika|s[uü]per|g[uü]zel|"
    r"(?:sen )?kimsin|ad[iı]n ne|ne(?:ler)? yapabilirsin|yard[iı]m(?: eder misin)?|"
    r"ho[sş][cç]a kal(?:[iı]n)?|g[oö]r[uü][sş][uü]r[uü]z|"
    r"thanks?(?: you)?|bye|good (?:morning|afternoon|evening)"
)
_ADDRESS = r"(?: (?:hocam|efendim|dostum|synapse))?"
# Longer than this, a message is more than a greeting even if every word is one.
SMALL_TALK_WORDS = 8
SMALL_TALK = re.compile(rf"(?:(?:{_PHRASES}){_ADDRESS})(?: (?:{_PHRASES}){_ADDRESS}){{0,2}}")


def small_talk(message: str) -> bool:
    """Whether the message is only a greeting, thanks or a farewell."""
    words = re.sub(r"[^\w\s]", " ", lower(message)).split()
    return 0 < len(words) <= SMALL_TALK_WORDS and SMALL_TALK.fullmatch(" ".join(words)) is not None


# A question about the collection itself, said plainly. Narrow on purpose (none of the golden
# set's 416 questions matches): the documents must be plural ("bu dosyada ne var" asks about
# one file), and "kaç belge" must be about what is there ("toplantıya kaç belge sunuldu" is a
# question to the documents). Other ways of asking reach the route ('library').
_DOC = r"(?:belge|dok[uü]man|dosya|evrak)(?:ler|lar)?(?:im|imiz|in|iniz)?"
_DOCS_IN = (
    r"(?:belge|dok[uü]man|dosya|evrak)(?:ler|lar)(?:imiz|ımız|im|ım|in|ın|iniz|ınız)?"
    r"(?:de|da|in|ın|nde|nda)?"
)
_LIBRARY = (
    rf"\b{_DOCS_IN}(?: (?:i[cç]inde|i[cç]erisinde))? (?:neler|ne) var\b",
    rf"\bhangi (?:{_DOC}|klas[oö]r(?:ler)?|koleksiyon(?:lar)?)(?:e|a|y[ae])? "
    r"(?:var|eri[sş]|bakabil|sahip|y[uü]kl)",
    rf"\bka[cç] (?:tane )?(?:{_DOC}|klas[oö]r)\w* (?:var|y[uü]kl|eklen|bulun|eri[sş])",
    rf"\b{_DOC}(?:i|ı|leri|ları)? (?:listesi|listele|s[iı]rala)",
    rf"\bne (?:t[uü]r|[cç]e[sş]it) {_DOC}",
    rf"\b(?:en )?son (?:y[uü]klenen|eklenen) {_DOC}",
    rf"\b(?:sistemde|k[uü]t[uü]phanede|elimizde) (?:neler var|ne var|hangi {_DOC}|ka[cç] {_DOC})",
    r"\b(?:neye|nelere) eri[sş]",
    r"\b(?:what|which|how many) (?:documents|files|folders)\b",
    r"\blist (?:the |my |all |our )?(?:documents|files)\b",
    r"\bwhat(?:'s| is) in (?:the|my|our) (?:documents|files|library)\b",
)
LIBRARY = re.compile("|".join(f"(?:{pattern})" for pattern in _LIBRARY))


def about_library(message: str) -> bool:
    """Whether the message asks about the collection itself: what, how many, which folders."""
    return LIBRARY.search(lower(message)) is not None
