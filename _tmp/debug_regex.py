#!/usr/bin/env python3
import re

FREE_LAW_RE = re.compile(
    r'(?<![가-힣a-zA-Z_0-9])'
    r'([가-힣a-zA-Z]+(?:[\s·&]{1,3}[가-힣a-zA-Z]+)*?(?:法|법|법률)(?:施?行?令|規則)?)'
    r'(?![가-힣a-zA-Z_0-9])'
)
text = "파견근로자 보호 등에 관한 법률 제6조의2를 인용한다."
print('정규화 키 mapping 확인:')
print('  정규식 전체 검색:')
m = FREE_LAW_RE.search(text)
print('  match:', m)
if m:
    print('  group0:', repr(m.group(0)), 'start:', m.start(), 'end:', m.end())
else:
    print('  매칭 없음')

# 문장에서 단어 연속 구간마다 매칭 시도
print()
print('문장 내 각 위치별 탐색:')
for i in range(len(text)):
    rem = text[i:]
    mm = FREE_LAW_RE.match(rem)
    if mm:
        print(f'  позиция {i}: matched {mm.group(0)!r}')
        break
else:
    print('  어디에서도 매칭 시작 안 됨')

# 개별 단어 수준에서 '(?:法|법|법률)'이 문구 끝에 오는 경우
print()
print('단어 연속 끝에만 법률/법/法이 오면 매칭되어야 함.')
print('실제: "파견근로자 보호 등에 관한 법률" - 여기까지 정규식 매칭 시도')
sub = text[:13]  # "파견근로자 보호 등에 관한 법률"
print(f'  부분: {sub!r}')
m2 = FREE_LAW_RE.search(sub)
print(f'  부분 매칭: {m2}')
if m2:
    print('  group0:', repr(m2.group(0)))
