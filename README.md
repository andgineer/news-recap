# Repository Coverage

[Full report](https://htmlpreview.github.io/?https://github.com/andgineer/news-recap/blob/python-coverage-comment-action-data/htmlcov/index.html)

| Name                                                     |    Stmts |     Miss |   Cover |   Missing |
|--------------------------------------------------------- | -------: | -------: | ------: | --------: |
| src/news\_recap/\_\_about\_\_.py                         |        1 |        0 |    100% |           |
| src/news\_recap/config.py                                |      285 |      193 |     32% |150-251, 256-258, 261-268, 271-307, 310-313, 316-330, 333-345, 350-373, 377-384, 388-418, 422, 435, 495, 516-536, 545-566, 570-580, 584-586, 593-601, 605-631 |
| src/news\_recap/http/fetcher.py                          |       42 |       20 |     52% |43-49, 59-82, 92, 95, 98 |
| src/news\_recap/http/html\_extractor.py                  |       29 |       18 |     38% |     35-74 |
| src/news\_recap/http/youtube\_extractor.py               |       94 |       60 |     36% |57, 61-62, 67-68, 73-76, 89-90, 95, 100, 114-128, 137-165, 188-209 |
| src/news\_recap/ingestion/cleaning.py                    |       53 |       33 |     38% |35-48, 59-65, 71-92, 98-99, 105 |
| src/news\_recap/ingestion/controllers.py                 |       66 |       38 |     42% |39-91, 94-140, 145-153, 160, 168, 175-177 |
| src/news\_recap/ingestion/language.py                    |       23 |       16 |     30% |     19-39 |
| src/news\_recap/ingestion/models.py                      |      149 |        0 |    100% |           |
| src/news\_recap/ingestion/pipeline.py                    |       35 |       17 |     51% |35-43, 51-75, 86 |
| src/news\_recap/ingestion/repository.py                  |      255 |      210 |     18% |52-62, 69-72, 79, 82-87, 90-93, 97-101, 105-110, 117-121, 124-125, 133-174, 177-182, 191-206, 215-235, 243-263, 270-304, 315-345, 352-364, 371-385, 388-395, 398-403, 410-418, 421-422, 430-435, 445-454, 462-467, 477-486, 495-513, 521-525, 542-545, 559, 583 |
| src/news\_recap/ingestion/services/fetch\_service.py     |       65 |       49 |     25% |38-41, 44-57, 72-129, 132-133 |
| src/news\_recap/ingestion/services/normalize\_service.py |       14 |        5 |     64% |22-23, 26-33 |
| src/news\_recap/ingestion/sources/base.py                |       31 |        4 |     87% |19, 46, 55, 64 |
| src/news\_recap/ingestion/sources/rss.py                 |      424 |      317 |     25% |45, 56, 70, 81, 91, 100, 165-169, 173-175, 179, 182-190, 197-222, 225-257, 260-317, 320-325, 334-339, 347-352, 355-380, 388-391, 399-405, 414-454, 458-460, 464-471, 480-503, 510-515, 519-543, 550-590, 594-632, 636-650, 654-663, 667-669, 673-678, 682-685, 689-690, 694-702, 706-719, 723-747, 751-754, 758-775, 785-799, 803-804 |
| src/news\_recap/main.py                                  |       80 |       72 |     10% |    17-390 |
| src/news\_recap/recap/agents/ai\_agent.py                |      161 |      129 |     20% |60-137, 141-144, 172-175, 180-186, 191-206, 214-221, 229-237, 246-253, 274-331, 339-350 |
| src/news\_recap/recap/agents/api\_agent.py               |       58 |       58 |      0% |     8-117 |
| src/news\_recap/recap/agents/concurrency.py              |       41 |       32 |     22% |40-49, 53-60, 64-66, 70-75, 79-85 |
| src/news\_recap/recap/agents/echo.py                     |       20 |       20 |      0% |     19-53 |
| src/news\_recap/recap/agents/routing.py                  |      131 |       87 |     34% |30, 52, 56, 62-74, 103-117, 129-168, 188-203, 218-255, 270, 274-276 |
| src/news\_recap/recap/agents/subprocess.py               |      162 |      130 |     20% |27-28, 60-94, 98-120, 129-140, 144-155, 159, 190-274, 278-281, 286-302, 306-317 |
| src/news\_recap/recap/agents/transport.py                |       10 |        0 |    100% |           |
| src/news\_recap/recap/agents/transport\_anthropic.py     |       19 |       14 |     26% |     18-39 |
| src/news\_recap/recap/article\_ordering.py               |       44 |       37 |     16% |16-33, 45-71, 83-88 |
| src/news\_recap/recap/contracts.py                       |       67 |       32 |     52% |49-50, 56-59, 65, 71-81, 87, 93-125, 131 |
| src/news\_recap/recap/dedup/calibration.py               |       66 |       38 |     42% |50-61, 71-95, 105-107, 113-143 |
| src/news\_recap/recap/dedup/cluster.py                   |       51 |       43 |     16% |29-50, 58-70, 78-91 |
| src/news\_recap/recap/dedup/embedder.py                  |       71 |       40 |     44% |23, 27-30, 40, 52, 55-72, 83-86, 89-91, 100-110, 116-120 |
| src/news\_recap/recap/export\_prompt.py                  |       77 |       66 |     14% |    23-173 |
| src/news\_recap/recap/flow.py                            |      103 |       82 |     20% |    37-180 |
| src/news\_recap/recap/launcher.py                        |       92 |       81 |     12% |    17-178 |
| src/news\_recap/recap/loaders/resource\_cache.py         |       51 |       38 |     25% |22, 29-30, 34-56, 70-81, 93-111 |
| src/news\_recap/recap/loaders/resource\_loader.py        |      138 |      104 |     25% |35, 62-70, 74-76, 89-132, 143-154, 157-168, 186-257, 264-272, 281-303, 312-313, 316, 319 |
| src/news\_recap/recap/models.py                          |       59 |       11 |     81% |25-26, 42-47, 50, 54, 59 |
| src/news\_recap/recap/pipeline\_setup.py                 |       38 |       22 |     42% |28, 61-92, 111-125 |
| src/news\_recap/recap/storage/pipeline\_io.py            |      154 |      104 |     32% |50, 54, 58, 66-67, 72, 77, 82-84, 105-113, 128-151, 156-181, 196-236, 250-264, 273-276, 281-283 |
| src/news\_recap/recap/storage/schemas.py                 |        1 |        1 |      0% |         7 |
| src/news\_recap/recap/storage/workdir.py                 |       53 |       37 |     30% |35, 45-76, 84-87, 96-104, 117-137 |
| src/news\_recap/recap/tasks/base.py                      |       69 |       32 |     54% |38-39, 44-49, 63-80, 110, 127-128, 133-151, 154 |
| src/news\_recap/recap/tasks/classify.py                  |      151 |      124 |     18% |63-102, 115-116, 133-145, 150-163, 177-205, 220-230, 233-293, 297-314 |
| src/news\_recap/recap/tasks/deduplicate.py               |      235 |      178 |     24% |59-63, 67-71, 87-101, 108-113, 122-132, 143-145, 159, 162-182, 185-197, 200-208, 212-219, 228-255, 260-280, 289-305, 318-380, 391-406, 419-420, 430-442, 452-456 |
| src/news\_recap/recap/tasks/enrich.py                    |      187 |      150 |     20% |65-85, 93-98, 107-123, 128-145, 155-158, 170-193, 208-210, 236-312, 326-330, 333-385, 393-402 |
| src/news\_recap/recap/tasks/group\_sections.py           |      110 |       89 |     19% |41-44, 62-84, 92-125, 133-141, 148-183, 191-192, 201-233 |
| src/news\_recap/recap/tasks/load\_resources.py           |       55 |       43 |     22% |38-47, 57-58, 63-125 |
| src/news\_recap/recap/tasks/map\_blocks.py               |      152 |      123 |     19% |35-50, 68-79, 88-89, 105-134, 143-151, 161, 170-208, 226-231, 241, 247-328 |
| src/news\_recap/recap/tasks/oneshot\_digest.py           |      314 |      250 |     20% |91, 98-103, 110-113, 116-120, 127-131, 134-139, 142-146, 149-150, 157-169, 176-179, 182-185, 192-222, 230-232, 249-285, 303-322, 331-349, 357-383, 391-423, 436-446, 454-464, 468-470, 485-519, 537-608, 617 |
| src/news\_recap/recap/tasks/parallel.py                  |       80 |       69 |     14% |33-38, 86-165, 175-180 |
| src/news\_recap/recap/tasks/prompts.py                   |       26 |        2 |     92% |     38-39 |
| src/news\_recap/recap/tasks/reduce\_blocks.py            |      226 |      183 |     19% |60-68, 76-81, 95-136, 141-146, 159-182, 190-191, 196-200, 213-216, 227-245, 253-263, 276-281, 288-295, 310, 313-331, 347-359, 367-443, 452-465 |
| src/news\_recap/recap/tasks/split\_blocks.py             |       92 |       72 |     22% |38-42, 51-79, 91-117, 126-188 |
| src/news\_recap/recap/tasks/summarize.py                 |       40 |       26 |     35% |34-41, 51-66, 75-90 |
| src/news\_recap/storage/io.py                            |       50 |       32 |     36% |21, 29-38, 43, 48, 60-62, 75-93 |
| src/news\_recap/web/server.py                            |       97 |       97 |      0% |     3-147 |
| **TOTAL**                                                | **5197** | **3728** | **28%** |           |


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