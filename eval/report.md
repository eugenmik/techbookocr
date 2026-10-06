# Model comparison on the reference set

| Model | CER↓ | WER↓ | Numbers F1↑ | TEDS↑ | TEDS-page↑ | Formulas CER↓ | Order↑ | Figures outside tables P/R | Sketches in tables R | sec/page | VRAM MiB | pages |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| hunyuan | 0.082 | 0.125 | 0.918 | 0.653 | 0.807 | 0.698 | 0.970 | — | — | 51.3 | 11383 | 31 |
| qwen9b_page | 0.221 | 0.259 | 0.892 | 0.569 | 0.726 | 0.856 | 0.971 | — | — | 53.0 | 9093 | 31 |
| dots_mocr | 0.150 | 0.170 | 0.882 | 0.824 | 0.915 | 0.412 | 0.958 | 1.00/1.00 | 0.00 (0/29) | 26.4 | 11861 | 31 |
| chandra2 | 0.180 | 0.206 | 0.874 | 0.752 | 0.792 | 0.521 | 0.950 | 1.00/1.00 | 0.31 (9/29) | 37.9 | 11806 | 31 |
| paddle_vl | 0.195 | 0.235 | 0.866 | 0.738 | 0.781 | 0.687 | 0.976 | 1.00/1.00 | 0.07 (2/29) | 34.0 | 7300 | 31 |

## By category

| Category | Model | CER↓ | Numbers F1↑ | TEDS↑ |
|---|---|---|---|---|
| figure | hunyuan | 0.126 | 0.938 | 0.549 |
| figure | qwen9b_page | 0.246 | 0.836 | 0.432 |
| figure | chandra2 | 0.363 | 0.818 | 0.603 |
| figure | paddle_vl | 0.292 | 0.814 | 0.724 |
| figure | dots_mocr | 0.256 | 0.811 | 0.675 |
| footnote | dots_mocr | 0.193 | 0.986 | 0.879 |
| footnote | qwen9b_page | 0.243 | 0.981 | 0.754 |
| footnote | chandra2 | 0.168 | 0.957 | 0.807 |
| footnote | paddle_vl | 0.154 | 0.939 | 0.720 |
| footnote | hunyuan | 0.124 | 0.912 | 0.701 |
| formula | chandra2 | 0.089 | 0.996 | 0.959 |
| formula | dots_mocr | 0.052 | 0.985 | 0.860 |
| formula | qwen9b_page | 0.060 | 0.982 | 0.461 |
| formula | paddle_vl | 0.071 | 0.959 | 0.625 |
| formula | hunyuan | 0.064 | 0.918 | 0.598 |
| list | dots_mocr | 0.038 | 1.000 | 0.995 |
| list | paddle_vl | 0.011 | 0.985 | 0.962 |
| list | qwen9b_page | 0.082 | 0.985 | 0.810 |
| list | chandra2 | 0.050 | 0.976 | 0.985 |
| list | hunyuan | 0.052 | 0.976 | 0.957 |
| poor_print | hunyuan | 0.012 | 0.979 | — |
| poor_print | qwen9b_page | 0.018 | 0.977 | — |
| poor_print | paddle_vl | 0.016 | 0.968 | — |
| poor_print | chandra2 | 0.058 | 0.954 | — |
| poor_print | dots_mocr | 0.022 | 0.953 | — |
| table | hunyuan | 0.129 | 0.875 | 0.650 |
| table | qwen9b_page | 0.345 | 0.839 | 0.650 |
| table | dots_mocr | 0.284 | 0.776 | 0.811 |
| table | chandra2 | 0.327 | 0.759 | 0.730 |
| table | paddle_vl | 0.394 | 0.746 | 0.779 |
| text | hunyuan | 0.033 | 0.985 | 0.936 |
| text | qwen9b_page | 0.057 | 0.981 | 0.500 |
| text | dots_mocr | 0.023 | 0.977 | 0.947 |
| text | paddle_vl | 0.022 | 0.961 | 0.499 |
| text | chandra2 | 0.033 | 0.955 | 0.959 |

## Errors

- qwen9b_page: 1 error
