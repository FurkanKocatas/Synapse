"""What the chat says when it does not answer from the documents (docs/design/answers.md):
a greeting answered in conversation, a message the search found nothing for judged by the
model (the route), an answer from general knowledge, a classic conversation; and when it is,
for the model, which does not know the day.
"""

import re
from datetime import datetime

from synapse.knowledge.public import lower

# Answers that rest on no document: a reply in conversation, or one from general knowledge.
CONVERSATION_SYSTEM = (
    "Sen Synapse'sin: bir kurumun belgelerinden, kaynağını göstererek soru cevaplayan bir "
    "asistan. Şu an belgelerden değil, sohbet olarak cevap veriyorsun. Kısa, sıcak ve doğal "
    "yaz; mesajın dilinde cevap ver. Kurumun belgeleri, kararları, bütçesi, kişileri ya da "
    "sayıları hakkında hiçbir bilgi uydurma; böyle bir şey sorulursa bunu belgelerde "
    "arayabileceğini söyle. Ne yapabildiğin sorulursa: kurumun belgelerinde arama yapıp "
    "cevabı kaynağıyla verebildiğini, belgeleri yükleyip düzenlemeye yardım ettiğini ve genel "
    "sorularda da yardımcı olabildiğini anlat. {when}"
)
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


ROUTE_SYSTEM = (
    "Bir kurumun belge asistanına gelen son mesajın türünü seç. 'conversation': selamlaşma, "
    "teşekkür, vedalaşma, asistanın kendisine dair bir soru (kim olduğu, ne yapabildiği) ya da "
    "bilgi istemeyen sohbet. 'general': kurumla ilgisi olmayan, genel bilgiyle cevaplanan bir "
    "soru (bir kavramın tanımı, bir hesaplama, bir programlama sorusu) ya da metin yazma, "
    "özetleme, çeviri isteği. 'documents': kurumun kendisi, birimleri, belgeleri, kararları, "
    "bütçesi, personeli, mevzuatı, tarihleri, sayıları ya da işleyişi hakkında her soru. Emin "
    "değilsen 'documents' seç."
)
ROUTE_SCHEMA = {
    "type": "object",
    "properties": {"kind": {"type": "string", "enum": ["conversation", "general", "documents"]}},
    "required": ["kind"],
}
ROUTE_TOKENS = 16
REPLY_TOKENS = 700
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
