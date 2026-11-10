# Census Table 1 — 면적과 인구 (표 이미지 → 문서)

- 출처: U.S. Census Bureau, 1910 Census report (published 1913) · PDF 2쪽 · 인쇄 22쪽
- 이용 조건: 미국 연방정부 발행 퍼블릭 도메인 자료 (과제 안내 기준)
- 입력: `input/census-table.png` (사본 `outputs/ocr/input_census-table.png`)
- 처리: PaddleOCR(영어)로 글자·좌표를 읽고, 좌표·괘선으로 행·열을 묶어 표를 만든 뒤 원본과 대조
- 표기: 값 뒤 `✎` = 원시 OCR을 원본 대조 후 수정, `⚠` = 확인 필요(미해결), 각주 번호는 ¹ ²처럼 표시

## 복원한 표

| Table 1 AREA | Gross area (land and water) in square miles | Population: 1910 |
|---|---:|---:|
| United States, with outlying possessions | 3,743,306 | 101,115,487 |
| United States, exclusive of outlying possessions | 3,026,789 | 91,972,266 |
| Outlying possessions | 716,517 | 9,143,221 |
| 　Alaska | 590,884 | 64,356 |
| 　Hawaii | 6,449 | 191,909 |
| 　Porto Rico | 3,435 | 1,118,012 |
| 　Military and naval service abroad | — | 55,608 |
| 　Philippine Islands | 115,026 | 7,635,426¹ ✎ |
| 　Panama Canal Zone | 436 | 62,810² ✎ |
| 　Guam (population estimated) | 210 | 9,000 |
| 　Samoa (population estimated) | 77 | 6,100 |

- 1 Population in 1903.
- 2 Population in 1912.

> 빈 칸 `—`: 원본에 값이 인쇄되어 있지 않음(군인·해군 복무자의 면적). 값을 추정해 채우지 않았습니다.

## 검토 기록 — 원시 인식 vs 원본 대조

(수정·특이 사항만 표시. 규칙으로 통과한 칸과 단순 일치 칸은 `review.json`에 모두 기록)

| 칸 | 행 이름 / 열 제목 | 원시 OCR | 최종 | 상태 | 근거·메모 |
|---|---|---|---|---|---|
| H0C0 |  / region | `Table 1 AREA` | Table 1 AREA | 원본 대조 일치 | 원본 대조: 'Table 1' / 'AREA.' (영어 모델은 정확히 읽음; 한국어 모델은 'able 1'로 오인식) |
| R0C2 | United States, with outlying possessions / population_1910 | `101, 115, 487` | 101,115,487 | 원본 대조 일치 | 원본 대조: 101, 115, 487 일치 (OCR 신뢰도 0.94) |
| R1C2 | United States, exclusive of outlying possessions / population_1910 | `91, 972, 266` | 91,972,266 | 원본 대조 일치 | 원본 대조: 91, 972, 266 일치 (OCR 신뢰도 0.94) |
| R4C2 | Hawaii / population_1910 | `191, 909` | 191,909 | 원본 대조 일치 | 원본 대조: 191, 909 일치 (OCR 신뢰도 0.95) |
| R5C2 | Porto Rico / population_1910 | `1, 118, 012` | 1,118,012 | 원본 대조 일치 | 원본 대조: 1, 118, 012 일치 (OCR 신뢰도 0.92) |
| R6C1 | Military and naval service abroad / gross_area_sq_mi | `` | —(비어 있음) | 원본에 값 없음 | 원본 대조: 이 칸에는 점선 리더만 있고 숫자가 인쇄되어 있지 않음. 면적 합계 검산도 이 칸을 0으로 두면 일치(716,517). |
| R7C2 | Philippine Islands / population_1910 | `17,635,426` | 7,635,426 | 수정함 | 원본 확대 대조: 숫자 앞의 작은 위첨자 ¹(각주 1)을 OCR이 숫자 1로 붙여 읽음. 합계 검산(속령 인구 9,143,221)도 일치. |
| R8C2 | Panama Canal Zone / population_1910 | `262, 810` | 62,810 | 수정함 | 원본 확대 대조: 숫자 앞의 위첨자 ²(각주 2)를 OCR이 숫자 2로 붙여 읽음. 합계 검산 일치. |
| N1 |  / note | `2 Population in 1012.` | 2 Population in 1912. | 수정함 | 원본 대조: 각주 2의 연도는 1912. OCR은 'Population in 1012'로 읽었고 신뢰도(0.97)가 높아 자동 규칙으로는 걸러지지 않음 — 사람 대조로만 발견. |

## 합계·순서 검산

원시 OCR 값 기준: 검산 4건 중 **불일치 1건** (불일치는 오인식 의심 칸을 찾는 단서로 사용)

| 범위 | 검산 | 총합 | 자식 합 | 차이 |
|---|---|---:|---:|---:|
| population_1910 | 속령 = 8개 지역 합 | 9,143,221 | 19,343,221 | -10,200,000 |

수정 반영 후 최종값 기준: 검산 4건 중 **일치 4건**


## 범위와 한계 (정직성 메모)

- 확인 필요(미해결) 칸: 없음
- 사람 대조 기록이 없는 규칙 통과(`auto_ok`) 칸: 0개. 신뢰도·형식·합계(·날짜 순서) 규칙만 통과한 값입니다. 규칙은 합계가 우연히 맞는 오류나 신뢰도가 높은 오인식(예: 각주 연도 `1912`→`1012`)을 못 잡을 수 있어 확정값으로 보면 안 됩니다.
- 대조는 코딩 에이전트(Claude)가 원본 이미지를 보고 1차로 수행했습니다. 제출자(사람)의 재확인이 필요하며, 의심 가는 칸은 `/review`에서 '확인 필요로 표시'하면 `table.csv`의 `needs_check` 열과 이 문서에 반영됩니다.
- 합계 역산·정규화·날짜 순서로 얻은 값은 '힌트'일 뿐이며, 원본 이미지와 대조한 뒤에만 `corrections.json`에 반영했습니다.
- 이미지 아래쪽의 웹페이지 캡션(`FRASER No. 11 — ...`)은 표가 아니므로 제외했습니다.
- 이 표는 3열·11행 구조를 가정한 합계 검산 규칙을 사용합니다.

## 파일

`table.csv`(최종 표) · `review.json`(칸별 원시값·좌표·상태) · `review_overlay.png`(원본 위 검토 표시) · `raw_ocr.json`·`ocr_lines.json`·`ocr_overlay.png`(원시 OCR) · `corrections.json`(사람 대조 기록) · `manifest.json`
