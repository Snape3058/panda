![](images/banner.png)

## From Compilation Database to Compiler-Based Tools.

*Panda* is a compilation-independent tooling scheduler
for pipelining compiler-based tools in parallel
based on the [JSON compilation database][link-cdb].
It allows you to execute various tools
on translation units by replaying the compilation process.
An introduction video to this tool is available from <https://youtu.be/dLG2tEzuaCw>.

The advantage of *Panda* include:

1. Avoiding interference with the build system;
2. Compatible to arbitrary compiler-based tools;
3. Scheduling tool execution in a dependency-free manner
    to take full advantages of the system resources.

## Installation

*Panda* is a standalone Python script.
You can install it by directly downloading file `panda` from this repo.

```
$ curl -fsSL https://github.com/Snape3058/panda/raw/demo/panda | sudo tee /usr/bin/panda >/dev/null
$ sudo chmod +x /usr/bin/panda
```

GitHub Repo for ISSTA tool demo revision: <https://github.com/Snape3058/panda/tree/demo>.
Please note that the content on the `demo` branch is ahead of the main branch.
And the functionalities on this branch will be merged to the main branch
after this tool paper gets accepted.

## Usage

Scheduling the execution of compiler-based tools requires the JSON Compilation Database.
Users can setup the environment according to the introduction from Clang
(<https://clang.llvm.org/docs/HowToSetupToolingForLLVM.html>)
or using tools like [Bear (Build EAR)][link-bear].

Executing *Panda* by providing the actions to be executed
together with number of parallel workers and output path (optional).

```
$ panda <actions> [-f CDB] [-j JOBS] [-o OUTPUT] [options]
```

The built-in actions are composed of compilation database actions,
which can generate output directly from the compilation database,
and tooling actions invoking compilers and tools.
These actions can cover most scenes of executing analyzers
and generating desired inputs for analyzers.

* Example 1: Generating external function map and invocation list
    to path `/tmp/csa-ctu-scan` under a concurrency of 16 processes.

```
$ panda -YM -j 16 -o /tmp/csa-ctu-scan
```

* Example 2: Executing a customized plugin description `/tmp/check/action.json`
    and store output to path `/tmp/check` without parallelization.

```
$ panda --plugin /tmp/check/action.json -o /tmp/check
```

### Built-in Compilation Database Actions

The compilation database actions
transform the input compilation database
to generate the output file,
or summarize the output of other tooling actions.

* Generate *input file list* (`-L` or `--gen-input-file-list`):
    a list of all unique `file`s with absolute path.
* Generate *source file list* (`-F` or `--gen-source-file-list`):
    a list of all unique source files and the header files included.
* Generate *invocation list* (`-Y` or `--gen-invocation-list`)
    for Cross Translation Unit Analysis of the *Clang Static Analyzer*
    under [on-demand-parsing][link-odp] strategy.
* Generate *external function map* (`-M` or `--gen-extdef-mapping`)
    for Cross Translation Unit Analysis of the *Clang Static Analyzer*
    under [on-demand-parsing][link-odp] strategy.
* Generate *external function map* (`-P` or `--gen-extdef-mapping-ast`)
    for Cross Translation Unit Analysis of the *Clang Static Analyzer*
    under [AST-loading][link-al] strategy.

### Built-in Compiler Actions

The compiler actions mainly generate inputs in desired formats for different analyzers.

* Test command line arguments and source file syntax (`-X` or `--syntax`):
    compiler action `-fsyntax-only -Wall`
* Re-compile the source file (`-C` or `--compile`):
    compiler action `-c`
* Generate preprocessed source file dump (`-E` or `--preprocess`):
    compiler action `-E`
* Generate Clang PCH format AST dump (`-A` or `--gen-ast`):
    clang compiler action `-emit-ast`
* Generate LLVM Bitcode in binary format (`-B` or `--gen-bc`):
    clang compiler action `-emit-llvm`
* Generate LLVM Bitcode in text cormat (`-R` or `--gen-ll`):
    clang compiler action `-emit-llvm -S`
* Generate assembly dump (`-S` or `--gen-asm`):
    compiler action `-S`
* Generate dependency description dump (`-D` or `--gen-dep`):
    compiler action `-M`
* Execute Clang Static Analyzer without Cross Translation Unit Analysis (`--analysis`)

### Built-in Tooling Actions

The tooling actions mainly invoke Clang AST based tools.

* Generating external function map (as mentioned above)

### Action Plugins

Users can execute customized compiler and tooling actions
with plugins defined with an action description in JSON format.
In the description,
field `comment` is a string for commenting the description,
field `type` determines the type of the action (compiler or tooling action),
and object `action` defines the action to be executed.

* Example compiler action (Figure 4a) of generating dependency files (option `-D` or `--gen-dep`).

```json
{
    "comment": "Example plugin for Panda driver.",
    "type": "CompilerAction",
    "action": {
        "prompt": "Generating dependency file",
        "args": ["-fsyntax-only", "-w", "-M"],
        "extname": ".d",
        "outopt": "-MF"
    }
}
```

For a compiler action, object `action` has four fields.
Field `prompt` defines the prompt string printed during executing the action.
Field `args` is a list of command line arguments to be added during execution.
Field `extname` determines the extension name of the output file.
And field `outopt` represents the option of generating the output.

* Example tooling action (Figure 4b) of executing Clang Tidy
    with a configuration file `config.txt` in output directory
    and storing command line output of stderr stream to output file.

```json
{
    "comment": "Example plugin for Panda driver",
    "type": "ClangToolAction",
    "action": {
        "prompt": "Generating raw external function map",
        "tool": "clang-tidy",
        "args": ["--config-file=/path/to/output/config.txt"],
        "extname": ".clang-tidy",
        "stream": "stderr"
    }
}
```

For a tooling action, object `action` has five fields.
Field `prompt`, `args`, and `extname` have the same meaning as a compile action.
Field `tool` determines the tool to be executed.
And field `stream` represents
the output of which stream will be stored to the output file.
Please note that, string `/path/to/output` will be always be replaced to
the actual output path determined with option `-o` during execution.

### Print Execution Summary and Gantt Chart

For ISSTA Tool Demo paper revision,
execution logs are dumped to the output path in the format of

```
/path/to/output/logs-<strategy>-<key>-<timestamp>
```

where `<strategy>` refers to the sorting strategies mentioned in Section 2.4
that `fifo` for *First-Come-First-Service*, and `ljf` for *Longest-Processing-Time-First*.
And `<key>` represent the key of sorting the worklist.
As mentioned in Section 2.3, the number of semicolons (`semicolon`) is used by default,
whereas the number of code lines (`loc`) is also available for alternative.

To summarize a previous execution and present the Gantt Chart of all workers,
please use the `analyze-log` script provided only in this branch.

```
$ analyze-log /path/to/output/logs-<strategy>-<key>-<timestamp>
```

The `analyze-log` requires [Matplotlib][link-matplotlib] to generate the Gantt Chart.
If the Python interpreter fails to import this module,
the `analyze-log` script will **NOT** report an error and exit.

An example Gantt Chart can be found from Figure 6 in the paper.

### Selection of Key to Sort the Worklist

We select the key to sort the worklist with Pearson Correlation Coefficient.
The detailed data of calculating the data is presented in the Google Spreadsheet below
(it may take a while to load the data).

<iframe src="https://docs.google.com/spreadsheets/d/e/2PACX-1vSf--XAfkfdPwY3p5K6QCjv-_yKoKUaV4tQcu9AiBvuOebHcZ8vuVsrGLuWseS4xQWZy3krDmX3PTlz/pubhtml?widget=true&amp;headers=false" width="800" height="600"></iframe>

## Acknowledgments

* REST team, Institute of Software, Chinese Academy of Sciences
* The tool name, *Panda*, is inspired by the animated sitcom *We Bare Bears*
    and the compiler argument recorder [Bear (Build EAR)][link-bear].

Let me know if *Panda* helps you. Thanks.


[link-bear]: https://github.com/rizsotto/Bear
[link-cdb]: https://clang.llvm.org/docs/JSONCompilationDatabase.html
[link-al]: https://clang.llvm.org/docs/analyzer/user-docs/CrossTranslationUnit.html#manual-ctu-analysis
[link-odp]: https://clang.llvm.org/docs/analyzer/user-docs/CrossTranslationUnit.html#id2
[link-matplotlib]: https://matplotlib.org
