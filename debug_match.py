import sys
sys.path.insert(0, '/c/Users/samkoo/Desktop/upstage/mabc-2026-final')

from service.core.match_claims import normalize_text, quote_exists_in_metadata, split_ellipsis

# ① normalize_text 확인
print("=== normalize_text ===")
r1 = normalize_text('  "Hello, World!"  ')
print(f"normalize_text('  \"Hello, World!\"  ') = {repr(r1)}")

r2 = normalize_text('_attention-based_')
print(f"normalize_text('_attention-based_') = {repr(r2)}")

r3 = normalize_text('"Attention is All You Need"')
print(f"normalize_text('\"Attention is All You Need\"') = {repr(r3)}")

# ② quote_exists_in_metadata 확인
print("\n=== quote_exists_in_metadata ===")
metadata = (
    'Attention Is All You Need',
    'We propose a new network architecture, the Transformer, based solely on '
    'attention mechanisms, dispensing with recurrence and convolutions entirely.',
)

q1 = 'The Transformer is based solely on attention mechanisms'
print(f"quote: {repr(q1)}")
print(f"result: {quote_exists_in_metadata(q1, metadata[0], metadata[1])}")

# 정규화 과정 확인
norm_meta = normalize_text(f"{metadata[0]} {metadata[1]}")
norm_q1 = normalize_text(q1)
print(f"norm_metadata: {repr(norm_meta)}")
print(f"norm_quote: {repr(norm_q1)}")
print(f"norm_quote in norm_metadata: {norm_q1 in norm_meta}")

# split_ellipsis 확인
parts = split_ellipsis(q1)
print(f"split_ellipsis(parts): {parts}")

# ③ 짧은 구절 확인
print("\n=== 짧은 구절 ===")
metadata2 = ('Test Paper', 'This is a short abstract for testing purposes only.')
q2 = 'short abstract'
print(f"quote: {repr(q2)} (len={len(q2)})")
print(f"result: {quote_exists_in_metadata(q2, metadata2[0], metadata2[1])}")
norm_q2 = normalize_text(q2)
print(f"norm_quote: {repr(norm_q2)} (len={len(norm_q2)})")
norm_meta2 = normalize_text(f"{metadata2[0]} {metadata2[1]}")
print(f"norm_metadata: {repr(norm_meta2)}")
print(f"norm_quote in norm_metadata: {norm_q2 in norm_meta2}")

# ④ BLEU 수치 확인
print("\n=== BLEU 수치 ===")
print(f"normalize_text('28.4') = {repr(normalize_text('28.4'))}")
print(f"normalize_text('BLEU') = {repr(normalize_text('bleu'))}")

# ⑤ 배치 테스트 확인
print("\n=== 배치 결과 확인 ===")
from service.core.match_claims import match_claims_batch
items = [
    {'claim': '트랜스포머는 어텐션 메커니즘 기반이다', 'metadata_title': 'Test', 'metadata_abstract': 'Test abstract', 'ref_id': 1},
]
results = match_claims_batch(items, use_cache=False, max_parallel=2)
print(f"results: {results}")
print(f"has ref_id: {'ref_id' in results[0] if results else 'N/A'}")
