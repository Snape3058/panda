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


# GenerateInput: generate the full path of input file
#
#   inputDir: the prefix of originalInput
#   originalInput: the input argument provided by JSON
def GenerateInput(inputDir, originalInput):
    if '/' == originalInput[0]:
        return originalInput
    if '/' == inputDir[-1]:
        return inputDir + originalInput
    else:
        return inputDir + '/' + originalInput


# GenerateOutput: generate the full path of output file with file type suffix
#
#   outputDir: the output argument provided in command arguments
#   originalOutput: the output argument provided by '-o' argument in JSON
#   suffix: the suffix representing its file type to replace '.o'
def GenerateOutput(outputDir, originalOutput, suffix):
    if '/' == outputDir[-1]:
        return outputDir + originalOutput + '.' + suffix
    else:
        return outputDir + '/' + originalOutput + '.' + suffix


# MakeCommand: replace the arguments with correct value for preprocess
#
#   opts: opts object (refer to ParseArguments)
#   command: the command object parsed from JSON
#   suffix: the suffix representing its file type to replace '.o'
#   additional: the additional arguments to do the corresponding preprocess
def MakeCommand(opts, command, suffix, additional):
    command = deepcopy(command)
    if 'cc' == command['arguments'][0][-2:]:
        command['arguments'][0] = opts['compiler']['cc']
    elif 'c++' == command['arguments'][0][-3:]:
        command['arguments'][0] = opts['compiler']['c++']
    else:
        print('What is this? ' + command['arguments'][0])
        assert False

    outputIndex = -1
    try:
        outputIndex = command['arguments'].index('-o') + 1
    except ValueError:
        outputIndex = len(command['arguments']) + 1
        command['arguments'].extend(['-o', command['file']+'.o'])
    command['arguments'][outputIndex] = GenerateOutput(
            opts['output'], command['arguments'][outputIndex], suffix)
    command['output'] = command['arguments'][outputIndex]

    inputIndex = command['arguments'].index(command['file'])
    command['arguments'][inputIndex] = GenerateInput(
            command['directory'], command['file'])

    command['arguments'] += additional

    return command


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

    outputIndex = arguments.index('-o') + 1
    outputDir = os.path.dirname(arguments[outputIndex])
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
                opts, job, 'ast', ['-emit-ast']))

        if opts['generate-i']:
            RunCommand(opts, MakeCommand(
                opts, job, 'i', ['-E']))

        if opts['generate-ll']:
            RunCommand(opts, MakeCommand(
                opts, job, 'll', ['-emit-llvm', '-S']))

        if opts['generate-bc']:
            RunCommand(opts, MakeCommand(
                opts, job, 'bc', ['-emit-llvm']))

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
