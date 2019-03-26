#!/usr/bin/env python3

import os
import sys
import json
import threadpool
from getopt import getopt
from copy import deepcopy
from subprocess import Popen as popen


HelpMsg = '''panda-- Generate .ast/.i/.ll/.bc files with output from bear.
Introduction:
  This program is used for preprocess the source code and generate the proper
  format of preprocessed files. It can generate preprocessed files in four
  kinds of formats:
    - <filename>.ast: the CPCH files in clang AST format
    - <filename>.i  : the compiler preprocessor output format
    - <filename>.ll : the LLVM-IR disassembly format
    - <filename>.bc : the LLVM bitcode format
  The program requires the input 'compile_commands.json' is in bear format.

Usage: panda [options]

Options:
  -A, --generate-ast
    Preprocess the source code to the CPCH files in clang AST format.

  -E, --generate-i
    Preprocess the source code to the compiler preprocessor output format.

  -S, --generate-ll
    Preprocess the source code to the LLVM-IR disassembly format.

  -B, --generate-bc
    Preprocess the source code to the LLVM bitcode format.

  -c <path_to_C_compiler>, --cc=<path_to_C_compiler>
    Customize the C compiler.

  -C <path_to_C++_compiler>, --c++=<path_to_C++_compiler>
    Customize the C++ compiler.

  -j <N>
    Customize job count, allow N jobs at once.

  -f <filename>
    Customize the input 'compile_commands.json' file.
    (default is './compile_commands.json')

  -o <output_dir>
    Customize the output directory.
    (default is './')

  -V
    Dump the command executed during execution.

  --dry-run
    Dump the command will be executed and exit.

  -v, --version
    Print the version information.

  -h, --help
    Print this message.
'''


VersionMsg = '''panda 1.0
Python ''' + sys.version


# ParseArguments: parse command line arguments with getopt.
#
# Refer to HelpMsg for more info, and remember to update HelpMsg when
# command line arguments are modified.
def ParseArguments(args):
    options, arguments = getopt(
            args[1:], 'hvVo:f:c:C:j:AESB', [
                'help', 'version', 'dry-run', 'cc', 'c++'
                'generate-ast', 'generate-i', 'generate-ll', 'generate-bc'
                ]
            )
    opts = {'verbose': False,
            'dry-run': False,
            'output': os.path.realpath('./'),
            'input': 'compile_commands.json',
            'compiler': {'cc': 'clang', 'c++': 'clang++'},
            'generate-i': False,
            'generate-ast': False,
            'generate-ll': False,
            'generate-bc': False,
            'jobs': 1,
            }
    for i in options:
        if '-h' == i[0] or '--help' == i[0]:
            print(HelpMsg)
            return {}
        elif '-v' == i[0] or '--version' == i[0]:
            print(VersionMsg)
            return {}
        elif '-V' == i[0]:
            opts['verbose'] = True
        elif '--dry-run' == i[0]:
            opts['dry-run'] = True
        elif '-o' == i[0]:
            opts['output'] = os.path.realpath(i[1])
        elif '-f' == i[0]:
            opts['input'] = i[1]
        elif '-c' == i[0] or '--cc' == i[0]:
            opts['compiler']['cc'] = i[1]
        elif '-C' == i[0] or '--c++' == i[0]:
            opts['compiler']['c++'] = i[1]
        elif '-j' == i[0]:
            try:
                jobcount = int(i[1])
                assert jobcount >= 1
                opts['jobs'] = jobcount
            except Exception:
                print('bad parameter for -j argument.')
        elif '-A' == i[0] or '--generate-ast' == i[0]:
            opts['generate-ast'] = True
        elif '-E' == i[0] or '--generate-i' == i[0]:
            opts['generate-i'] = True
        elif '-S' == i[0] or '--generate-ll' == i[0]:
            opts['generate-ll'] = True
        elif '-B' == i[0] or '--generate-bc' == i[0]:
            opts['generate-bc'] = True
        else:
            print("Bad option '" + i[0] + "'.")
            print(HelpMsg)
            return {}
    return opts


# RecoverOriginalFileName: recover the original absolute file name in command
#
#   directory: the directory where the compilation happened
#           e.g. json['directory']
#   filename: the filename to be parsed (can be both relative and absolute)
#           e.g. input file (json['file']), output file (-o value)
#                include directory (-I value)
#
#   return: if filename is relative path, then concatenate them
#           if is absolute path, then drop directory and return filename directly
def RecoverOriginalFileName(directory, filename):
    return os.path.abspath(os.path.join(directory, filename))


# GenerateCompiler: generate the preprocessor compiler
#
#   command: the original command object to be processed
#
#   return: the preprocessor compiler
def GenerateCompiler(opts, command):
    # check suffix only as the compiler argument can be full path
    if 'cc' == command['arguments'][0][-2:]:
        return opts['compiler']['cc']
    elif 'c++' == command['arguments'][0][-3:]:
        return opts['compiler']['c++']
    else:
        assert False, 'What is this compiler? ' + command['arguments'][0]


# GenerateOutput: generate the full path of output file with file type suffix
#
#   outputDir: the output argument provided in command arguments
#   originalOutput: the recovered output filename
#   suffix: the suffix representing its file type to replace '.o'
#
#   return: the absolute path of the output file in format:
#           /outputdir/absolute/path/to/output/file.suffix
def GenerateOutput(outputDir, workspace, originalOutput, suffix):
    recoveredOutput = RecoverOriginalFileName(workspace, originalOutput)
    return os.path.join(outputDir, recoveredOutput[1:]) + '.' + suffix


# MakeCommand: replace the arguments with correct value for preprocess
#
#   opts: opts object (refer to ParseArguments)
#   command: the command object parsed from JSON
#   suffix: the suffix representing its file type to replace '.o'
#   additional: the additional arguments to do the corresponding preprocess
#
#   return: command object
#       the command object is defined as follows:
#           - arguments: list of arguments to be executed by compiler
#           - directory: compiler working directory
#           - output: directory of -o parameter
def MakeCommand(opts, command, suffix, additional, keptArgs):
    arguments = [GenerateCompiler(opts, command)]

    # append additional arguments for generating targets
    arguments += additional

    # generate arguments
    i = iter(command['arguments'])
    while True:
        A = next(i, None)
        if A is None:
            break

        # remove output argument if it has
        if '-o' == A:
            A = next(i)

        # generate the argument should be kept
        else:
            for kept in keptArgs:
                head = A[:len(kept)]
                if kept == head:
                    if head == A:
                        arguments.append(A + next(i))
                    else:
                        arguments.append(A)

    # append output argument
    output = GenerateOutput(opts['output'], command['directory'],
            command['file'], suffix)
    arguments += ['-o', output]

    # append input argument
    arguments.append(RecoverOriginalFileName(
        command['directory'], command['file']))

    return {'directory': command['directory'],
            'arguments': arguments,
            'output': output}


# RunCommand: run the command to do the preprocess
#
#   opts: opts object (refer to ParseArguments)
#   command: the command object to be executed. (in the parsed JSON format)
def RunCommand(opts, command):
    print('Generating "' + command['output'] + '"')

    arguments = command['arguments']
    if opts['verbose'] or opts['dry-run']:
        print(arguments)

    if opts['dry-run']:
        return

    outputDir = os.path.dirname(command['output'])
    if not os.path.exists(outputDir):
        try:
            os.makedirs(outputDir)
        except FileExistsError:  # may happen when multi-thread
            pass

    process = popen(arguments, cwd=command['directory'])
    process.wait()


# PreprocessProject: monitor and control the process of preprocess
#
#   opts: opts object (refer to ParseArguments)
def PreprocessProject(opts):
    if not opts:
        return

    def jobRun(opts, job):
        if opts['generate-ast']:
            RunCommand(opts, MakeCommand(
                opts, job, 'ast', ['-emit-ast'],
                ['-std', '-D', '-U', '-I']))

        if opts['generate-i']:
            RunCommand(opts, MakeCommand(
                opts, job, 'i', ['-E'],
                ['-std', '-D', '-U', '-I']))

        if opts['generate-ll']:
            RunCommand(opts, MakeCommand(
                opts, job, 'll', ['-c', '-g', '-emit-llvm', '-S'],
                ['-std', '-D', '-U', '-I', '-f', '-m']))

        if opts['generate-bc']:
            RunCommand(opts, MakeCommand(
                opts, job, 'bc', ['-c', '-g', '-emit-llvm'],
                ['-std', '-D', '-U', '-I', '-f', '-m']))

    if not os.path.exists(opts['output']):
        os.makedirs(opts['output'])

    jobList = json.load(open(opts['input'], 'r'))

    if 1 == opts['jobs']:
        for i in jobList:
            jobRun(opts, i)
    else:
        pool = threadpool.ThreadPool(opts['jobs'])
        reqs = threadpool.makeRequests(
                jobRun, [([opts, i], None) for i in jobList])
        for i in reqs:
            pool.putRequest(i)
        pool.wait()


def main(args):
    opts = ParseArguments(args)
    PreprocessProject(opts)


if '__main__' == __name__:
    main(sys.argv)
