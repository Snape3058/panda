#!/usr/bin/env python3

import os
import sys
import json
import threadpool
import argparse
from subprocess import Popen as popen


# default configurations and strings
class Default:
    # configurable names, tags, and other strings
    ast = 'Clang PCH file'
    i = 'C/C++ preprocessed file'
    ll = 'LLVM IR file'
    bc = 'LLVM BitCode file'
    fm = 'Clang function-mapping file'
    Version = '2.0'
    Commit = '%REPLACE_COMMIT_INFO%'
    Now = '%REPLACE_NOW%'

    # program description
    DescriptionMsg = '''Generate preprocessed files from compilation database.

This program is used for preprocessing C/C++ source code files with the
help of Clang compilation database. It can generate preprocessed files in
the following kinds of formats:
  - <filename>.ast    : the {}
  - <filename>.i      : the {}
  - <filename>.ll     : the {}
  - <filename>.bc     : the {}
  - externalFnMap.txt : the {}
'''.format(ast, i, ll, bc, fm)

    # program version info
    VersionMsg = '''panda {} ({})
Provided by REST team, ISCAS.
Copyright 2018-{}. All rights reserved.'''.format(
            Version, Commit, Now)


# ParseArguments: parse command line arguments with argparse.
def ParseArguments(args):
    parser = argparse.ArgumentParser(description=Default.DescriptionMsg,
            formatter_class=argparse.RawTextHelpFormatter)
    parser.add_argument('-v', '--version', action='version', version=Default.VersionMsg)
    parser.add_argument('-V', '--verbose', action='store_true', dest='verbose',
            help='Verbose output mode.')
    parser.add_argument('-A', '--generate-ast', action='store_true', dest='ast',
            help='Generate {}.'.format(Default.ast))
    parser.add_argument('-E', '--generate-i', action='store_true', dest='i',
            help='Generate {}.'.format(Default.i))
    parser.add_argument('-S', '--generate-ll', action='store_true', dest='ll',
            help='Generate {}.'.format(Default.ll))
    parser.add_argument('-B', '--generate-bc', action='store_true', dest='bc',
            help='Generate {}.'.format(Default.bc))
    parser.add_argument('-M', '--generate-fm', action='store_true', dest='fm',
            help='Generate {}.'.format(Default.fm))
    parser.add_argument('-P', '--copy-file', action='store_true', dest='cp',
            help='Copy source code file to output directory.')
    parser.add_argument('-o', '--output',
            type=str, dest='output', default=os.path.abspath('./'),
            help='Customize the output directory. (default is "./")')
    parser.add_argument('-f', '--database', metavar='<compile_commands.json>',
            type=str, dest='input', default=os.path.abspath('./compile_commands.json'),
            help='Customize the compilation database file.')
    parser.add_argument('-c', '--cc',
            type=str, dest='cc', default='clang',
            help='Customize the C compiler. (default is clang)')
    parser.add_argument('-C', '--cxx',
            type=str, dest='cxx', default='clang++',
            help='Customize the C++ compiler. (default is clang++)')
    parser.add_argument('-m', '--fnmapping',
            type=str, dest='fnmapping', default='clang-func-mapping',
            help='Customize the function mapping scanner. (default is clang-func-mapping)')
    parser.add_argument('-j', '--jobs', type=int, dest='jobs', default=1,
            help='Customize the number of jobs allowed in parallel.')
    parser.add_argument('--dump', action='store_true', dest='dump',
            help='Generate and dump commands to stdout only.')
    parser.add_argument('--ctu', action='store_true', dest='ctu',
            help='Alias to -M -A -P.')
    return parser.parse_args(args[1:])


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
        return opts.cc
    elif 'c++' == command['arguments'][0][-3:]:
        return opts.cxx
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
    output = GenerateOutput(opts.output, command['directory'],
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
    if opts.verbose or opts.dump:
        print(arguments)

    if opts.dump:
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
    def jobRun(opts, job):
        if opts.ast:
            RunCommand(opts, MakeCommand(
                opts, job, 'ast', ['-emit-ast'],
                ['-std', '-D', '-U', '-I']))

        if opts.i:
            RunCommand(opts, MakeCommand(
                opts, job, 'i', ['-E'],
                ['-std', '-D', '-U', '-I']))

        if opts.ll:
            RunCommand(opts, MakeCommand(
                opts, job, 'll', ['-c', '-g', '-emit-llvm', '-S'],
                ['-std', '-D', '-U', '-I', '-f', '-m']))

        if opts.bc:
            RunCommand(opts, MakeCommand(
                opts, job, 'bc', ['-c', '-g', '-emit-llvm'],
                ['-std', '-D', '-U', '-I', '-f', '-m']))

    if not os.path.exists(opts.output):
        os.makedirs(opts.output)

    jobList = json.load(open(opts.input, 'r'))

    if 1 == opts.jobs:
        for i in jobList:
            jobRun(opts, i)
    else:
        pool = threadpool.ThreadPool(opts.jobs)
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
