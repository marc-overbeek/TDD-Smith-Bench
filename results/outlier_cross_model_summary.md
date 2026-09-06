# Outlier Comparison Summary

## Selected LOC Outliers

| Rank | Repo | Model | Attempt | Net LOC | Complexity | Success | Case ID |
|---:|---|---|---:|---:|---:|---|---|
| 1 | oauthlib__oauthlib.1fd52536 | Qwen3 Coder 30B | 1 | -212 | 0 | success | oauthlib__oauthlib.1fd52536|oauthlib__oauthlib.1fd52536.empty_body_test_case_00103_c387e0613c|attempt_1 |
| 2 | seperman__deepdiff.ed252022 | Claude Haiku 4.5 | 1 | 104 | 0 | success | seperman__deepdiff.ed252022|seperman__deepdiff.ed252022.empty_body_from_scratch_00148_674fe43e19|attempt_1 |
| 3 | tkrajina__gpxpy.09fc46b3 | Claude Haiku 4.5 | 1 | 74 | 4 | success | tkrajina__gpxpy.09fc46b3|tkrajina__gpxpy.09fc46b3.empty_body_from_scratch_00071_7f46ded174|attempt_1 |

## Selected Complexity Outliers

| Rank | Repo | Model | Attempt | Complexity | Net LOC | Success | Case ID |
|---:|---|---|---:|---:|---:|---|---|
| 1 | tkrajina__gpxpy.09fc46b3 | Claude Haiku 4.5 | 1 | 33 | 0 | success | tkrajina__gpxpy.09fc46b3|tkrajina__gpxpy.09fc46b3.empty_body_from_scratch_00179_c63ffd1aab|attempt_1 |
| 2 | seperman__deepdiff.ed252022 | Claude Haiku 4.5 | 1 | -20 | 5 | success | seperman__deepdiff.ed252022|seperman__deepdiff.ed252022.empty_body_from_scratch_00141_07684178be|attempt_1 |
| 3 | facebookresearch__fvcore.a491d5b9 | Qwen3 Coder 30B | 1 | 17 | 16 | success | facebookresearch__fvcore.a491d5b9|facebookresearch__fvcore.a491d5b9.empty_body_from_scratch_00118_dbf0b24e41|attempt_1 |

## Cross-Model Case Comparison

| Metric Type | Case ID | Model | Exists | Success | Net LOC | Complexity | Patch Found | Fixed/Empty |
|---|---|---|---|---|---:|---:|---|---|
| complexity | facebookresearch__fvcore.a491d5b9|facebookresearch__fvcore.a491d5b9.empty_body_from_scratch_00118_dbf0b24e41|attempt_1 | Claude Haiku 4.5 | True | success | 18 | 6 | True | 37/37 |
| complexity | facebookresearch__fvcore.a491d5b9|facebookresearch__fvcore.a491d5b9.empty_body_from_scratch_00118_dbf0b24e41|attempt_1 | Claude Sonnet 4.6 | True | success | 17 | 4 | True | 37/37 |
| complexity | facebookresearch__fvcore.a491d5b9|facebookresearch__fvcore.a491d5b9.empty_body_from_scratch_00118_dbf0b24e41|attempt_1 | Qwen3 Coder 30B | True | success | 16 | 17 | True | 37/37 |
| complexity | seperman__deepdiff.ed252022|seperman__deepdiff.ed252022.empty_body_from_scratch_00141_07684178be|attempt_1 | Claude Haiku 4.5 | True | success | 5 | -20 | True | 35/35 |
| complexity | seperman__deepdiff.ed252022|seperman__deepdiff.ed252022.empty_body_from_scratch_00141_07684178be|attempt_1 | Claude Sonnet 4.6 | True | success | 0 | 0 | True | 35/35 |
| complexity | seperman__deepdiff.ed252022|seperman__deepdiff.ed252022.empty_body_from_scratch_00141_07684178be|attempt_1 | Qwen3 Coder 30B | True | success | 0 | 0 | True | 35/35 |
| complexity | tkrajina__gpxpy.09fc46b3|tkrajina__gpxpy.09fc46b3.empty_body_from_scratch_00179_c63ffd1aab|attempt_1 | Claude Haiku 4.5 | True | success | 0 | 33 | True | 2/2 |
| complexity | tkrajina__gpxpy.09fc46b3|tkrajina__gpxpy.09fc46b3.empty_body_from_scratch_00179_c63ffd1aab|attempt_1 | Claude Sonnet 4.6 | True | success | 0 | 1 | True | 2/2 |
| complexity | tkrajina__gpxpy.09fc46b3|tkrajina__gpxpy.09fc46b3.empty_body_from_scratch_00179_c63ffd1aab|attempt_1 | Qwen3 Coder 30B | True | success | 0 | 0 | True | 2/2 |
| loc | oauthlib__oauthlib.1fd52536|oauthlib__oauthlib.1fd52536.empty_body_test_case_00103_c387e0613c|attempt_1 | Claude Haiku 4.5 | True | success | -212 | 0 | True | 2/2 |
| loc | oauthlib__oauthlib.1fd52536|oauthlib__oauthlib.1fd52536.empty_body_test_case_00103_c387e0613c|attempt_1 | Claude Sonnet 4.6 | True | success | -212 | 0 | True | 2/2 |
| loc | oauthlib__oauthlib.1fd52536|oauthlib__oauthlib.1fd52536.empty_body_test_case_00103_c387e0613c|attempt_1 | Qwen3 Coder 30B | True | success | -212 | 0 | True | 2/2 |
| loc | seperman__deepdiff.ed252022|seperman__deepdiff.ed252022.empty_body_from_scratch_00148_674fe43e19|attempt_1 | Claude Haiku 4.5 | True | success | 104 | 0 | True | 23/23 |
| loc | seperman__deepdiff.ed252022|seperman__deepdiff.ed252022.empty_body_from_scratch_00148_674fe43e19|attempt_1 | Claude Sonnet 4.6 | True | success | 1 | 0 | True | 23/23 |
| loc | seperman__deepdiff.ed252022|seperman__deepdiff.ed252022.empty_body_from_scratch_00148_674fe43e19|attempt_1 | Qwen3 Coder 30B | True | success | 1 | 0 | True | 23/23 |
| loc | tkrajina__gpxpy.09fc46b3|tkrajina__gpxpy.09fc46b3.empty_body_from_scratch_00071_7f46ded174|attempt_1 | Claude Haiku 4.5 | True | success | 74 | 4 | True | 10/10 |
| loc | tkrajina__gpxpy.09fc46b3|tkrajina__gpxpy.09fc46b3.empty_body_from_scratch_00071_7f46ded174|attempt_1 | Claude Sonnet 4.6 | True | success | 5 | 5 | True | 10/10 |
| loc | tkrajina__gpxpy.09fc46b3|tkrajina__gpxpy.09fc46b3.empty_body_from_scratch_00071_7f46ded174|attempt_1 | Qwen3 Coder 30B | True | success | 12 | 10 | True | 10/10 |
