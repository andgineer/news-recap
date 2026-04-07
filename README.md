# Repository Coverage

[Full report](https://htmlpreview.github.io/?https://github.com/andgineer/news-recap/blob/python-coverage-comment-action-data/htmlcov/index.html)

| Name                                                     |    Stmts |     Miss |   Cover |   Missing |
|--------------------------------------------------------- | -------: | -------: | ------: | --------: |
| src/news\_recap/\_\_about\_\_.py                         |        1 |        0 |    100% |           |
| src/news\_recap/automation.py                            |      250 |       15 |     94% |82, 113-114, 170-173, 194-196, 207-210, 554 |
| src/news\_recap/config.py                                |      284 |       55 |     81% |236-238, 253, 255, 261, 276, 279, 284, 305, 307, 309, 311, 315, 317, 357, 364, 380, 382, 392-393, 397, 478, 480, 488, 503-520, 529, 531, 547-555, 561, 571, 578, 585 |
| src/news\_recap/http/fetcher.py                          |       42 |        4 |     90% |47, 92, 95, 98 |
| src/news\_recap/http/html\_extractor.py                  |       29 |        7 |     76% |47-49, 60-62, 69 |
| src/news\_recap/http/youtube\_extractor.py               |       94 |       15 |     84% |116-120, 140, 144, 158, 160-165, 190, 198 |
| src/news\_recap/ingestion/cleaning.py                    |       53 |        1 |     98% |        75 |
| src/news\_recap/ingestion/controllers.py                 |       40 |        1 |     98% |        91 |
| src/news\_recap/ingestion/language.py                    |       23 |        2 |     91% |    21, 35 |
| src/news\_recap/ingestion/models.py                      |      149 |        0 |    100% |           |
| src/news\_recap/ingestion/pipeline.py                    |       34 |        0 |    100% |           |
| src/news\_recap/ingestion/repository.py                  |      264 |       27 |     90% |91, 206, 216-236, 248, 317, 395, 553-554 |
| src/news\_recap/ingestion/services/fetch\_service.py     |       65 |        2 |     97% |   79, 120 |
| src/news\_recap/ingestion/services/normalize\_service.py |       14 |        0 |    100% |           |
| src/news\_recap/ingestion/sources/base.py                |       31 |        3 |     90% |46, 55, 64 |
| src/news\_recap/ingestion/sources/rss.py                 |      437 |       41 |     91% |47, 58, 72, 83, 93, 102, 201, 326, 340, 353, 377-382, 403, 405, 439, 449, 453, 457, 550-551, 557-558, 566-579, 761, 766, 770, 789-790, 800, 808 |
| src/news\_recap/main.py                                  |      327 |       16 |     95% |287, 352, 397, 404, 432, 527-528, 613-616, 633-638, 666, 702, 805, 807 |
| src/news\_recap/recap/agents/ai\_agent.py                |      161 |       51 |     68% |60-142, 146-149, 179, 185-191, 206-207, 302, 317, 336-342 |
| src/news\_recap/recap/agents/api\_agent.py               |       58 |        1 |     98% |        79 |
| src/news\_recap/recap/agents/concurrency.py              |       41 |        0 |    100% |           |
| src/news\_recap/recap/agents/routing.py                  |      131 |       14 |     89% |52, 73, 111, 117, 161, 166, 193, 228, 231, 233, 235, 237, 241, 248 |
| src/news\_recap/recap/agents/subprocess.py               |      162 |       42 |     74% |27-28, 62, 73, 85-86, 93, 110-111, 130, 132, 136, 139, 150-151, 153, 242-254, 257-269, 272-274, 278-281, 291, 296-297, 308-309, 312-317 |
| src/news\_recap/recap/agents/transport.py                |       10 |        0 |    100% |           |
| src/news\_recap/recap/agents/transport\_anthropic.py     |       19 |        1 |     95% |        35 |
| src/news\_recap/recap/article\_ordering.py               |       44 |        0 |    100% |           |
| src/news\_recap/recap/contracts.py                       |       71 |        6 |     92% |74, 92, 94, 96, 126-127 |
| src/news\_recap/recap/dedup/calibration.py               |       66 |       32 |     52% |71-95, 105-107, 113-143 |
| src/news\_recap/recap/dedup/cluster.py                   |       51 |        2 |     96% |    62, 66 |
| src/news\_recap/recap/dedup/embedder.py                  |       71 |       15 |     79% |27-30, 40, 58, 61, 83-86, 89-91, 110, 117 |
| src/news\_recap/recap/digest\_info.py                    |      142 |       11 |     92% |28, 82-84, 102, 119, 190, 192-197 |
| src/news\_recap/recap/export\_prompt.py                  |      116 |        4 |     97% |152, 264, 268-269 |
| src/news\_recap/recap/flow.py                            |      109 |       68 |     38% |67-71, 82-87, 91-94, 107-217 |
| src/news\_recap/recap/launcher.py                        |      211 |       15 |     93% |96, 209, 212-213, 241-242, 244, 248, 251-253, 359, 372, 410-411 |
| src/news\_recap/recap/loaders/resource\_cache.py         |       51 |        0 |    100% |           |
| src/news\_recap/recap/loaders/resource\_loader.py        |      138 |       18 |     87% |90, 121-127, 190-207, 211-213, 235, 257, 303, 312-313, 316, 319 |
| src/news\_recap/recap/models.py                          |       61 |        8 |     87% |42-47, 50, 59 |
| src/news\_recap/recap/pipeline\_setup.py                 |      226 |        9 |     96% |54-56, 145-146, 173-174, 329-330 |
| src/news\_recap/recap/storage/pipeline\_io.py            |      157 |       15 |     90% |74, 111-117, 140, 146-147, 161, 213, 224, 260 |
| src/news\_recap/recap/storage/workdir.py                 |       48 |        4 |     92% |     90-93 |
| src/news\_recap/recap/tasks/base.py                      |       73 |       22 |     70% |77-94, 124, 147-165, 168 |
| src/news\_recap/recap/tasks/classify.py                  |      152 |       20 |     87% |140, 146, 222-232, 240, 247-248, 253, 297-299 |
| src/news\_recap/recap/tasks/deduplicate.py               |      236 |       94 |     60% |60-64, 68-72, 109-114, 230-257, 265-285, 294-310, 323-390, 401-416, 464 |
| src/news\_recap/recap/tasks/enrich.py                    |      188 |       15 |     92% |145, 212, 239-240, 303-308, 328-332, 342, 355-356, 398 |
| src/news\_recap/recap/tasks/load\_resources.py           |       55 |        6 |     89% |42, 81-82, 88-90 |
| src/news\_recap/recap/tasks/oneshot\_digest.py           |      361 |      132 |     63% |162, 169-172, 198, 252-288, 306-327, 336-354, 362-388, 396-428, 519, 644-720, 729 |
| src/news\_recap/recap/tasks/parallel.py                  |       80 |       19 |     76% |37-38, 95-96, 102, 121-128, 150, 157-160, 180 |
| src/news\_recap/recap/tasks/prompts.py                   |       21 |        0 |    100% |           |
| src/news\_recap/recap/tasks/refine\_layout.py            |      115 |       24 |     79% |216-255, 262 |
| src/news\_recap/storage/io.py                            |       50 |        5 |     90% | 35-38, 61 |
| src/news\_recap/web/server.py                            |      129 |       31 |     76% |32-34, 60-62, 71-72, 90, 94-96, 142-143, 162, 182-206 |
| **TOTAL**                                                | **5741** |  **873** | **85%** |           |


## Setup coverage badge

Below are examples of the badges you can use in your main branch `README` file.

### Direct image

[![Coverage badge](https://raw.githubusercontent.com/andgineer/news-recap/python-coverage-comment-action-data/badge.svg)](https://htmlpreview.github.io/?https://github.com/andgineer/news-recap/blob/python-coverage-comment-action-data/htmlcov/index.html)

This is the one to use if your repository is private or if you don't want to customize anything.

### [Shields.io](https://shields.io) Json Endpoint

[![Coverage badge](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/andgineer/news-recap/python-coverage-comment-action-data/endpoint.json)](https://htmlpreview.github.io/?https://github.com/andgineer/news-recap/blob/python-coverage-comment-action-data/htmlcov/index.html)

Using this one will allow you to [customize](https://shields.io/endpoint) the look of your badge.
It won't work with private repositories. It won't be refreshed more than once per five minutes.

### [Shields.io](https://shields.io) Dynamic Badge

[![Coverage badge](https://img.shields.io/badge/dynamic/json?color=brightgreen&label=coverage&query=%24.message&url=https%3A%2F%2Fraw.githubusercontent.com%2Fandgineer%2Fnews-recap%2Fpython-coverage-comment-action-data%2Fendpoint.json)](https://htmlpreview.github.io/?https://github.com/andgineer/news-recap/blob/python-coverage-comment-action-data/htmlcov/index.html)

This one will always be the same color. It won't work for private repos. I'm not even sure why we included it.

## What is that?

This branch is part of the
[python-coverage-comment-action](https://github.com/marketplace/actions/python-coverage-comment)
GitHub Action. All the files in this branch are automatically generated and may be
overwritten at any moment.