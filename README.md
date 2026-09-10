Made using most of the code present in https://swesmith.com/

Added a few scripts to help creating empty task instances and to regenerate the code based on the failing tests, together with some scripts to analyse the resulting data.

For the data, we used 3 different models to generate the code

model name ending in wxnknl6gvktb was Haiku 4.5
model name ending in gewiaj6mtzjm was Qwen3 coder 30b
model name ending in ql4mbrrqznnz was Sonnet 4.6

As can be made up from the naming scheme of the data, we used amazon bedrock as host for these models.

Pipeline order:
First, download a working docker image of any repository.
run generate_empty_body_changes.py to generate tasks of the repository.
arguments:
    repo
    --workers 
    --max_functions
    --max_tests_per_line


after generatating the tasks, you can generate and validate the solutions
run generate_regen_from_tests.py te generate the code using the testcases
arguments:
        --config_file 
        --model
        --max_bugs
        --max_attempts
        --workers
        --include_combined
        --combined_only
        --combined_config_file

The execution of these two files contain the full execution of the pipeline, the remainder of the scripts were used to either create plots, extract metrics or fix some problems during development. 

After running the pipeline patch_metrics.py can be ran to extract the relevant metrics from the results.

