#!/usr/bin/env python3

import os
import sys
import json
import threadpool
import argparse
from subprocess import Popen as popen
from subprocess import PIPE as pipe
import re


# default configurations and strings
class Default:  # {{{
    # configurable names, tags, and other strings
    ast = 'Clang PCH file'
    i = 'C/C++ preprocessed file'
    ll = 'LLVM IR file'
    bc = 'LLVM BitCode file'
    fm = 'Clang function-mapping file'
    si = 'source code index file'
    filterstr = [
            '-o:',
            '-O([0123sg]|fast)?',
            '-Werror(=.+)?',
            '-W(all|extra)?',
            '-fsyntax-only',
            '-g',
            '.+\\.o(bj)?',
            ]
    Version = '2.0'
    Commit = '%REPLACE_COMMIT_INFO%'
    Now = '%REPLACE_NOW%'
    cc = 'clang'
    cxx = 'clang++'
    cfm = 'clang-func-mapping'
    fmname = 'externalFnMap.txt'
    srcidx = 'sources.txt'

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
  - {:<17} : the {}
'''.format(ast, i, ll, bc, fm, srcidx, si)

    # program version info
    VersionMsg = '''panda {} ({})
Provided by REST team, ISCAS.
Copyright 2018-{}. All rights reserved.'''.format(
            Version, Commit, Now)

    # }}}


# ParseArguments: parse command line arguments with argparse.
def ParseArguments(args):  # {{{
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
    parser.add_argument('-L', '--list-files', action='store_true', dest='ls',
            help='List source code file names to index file.')
    parser.add_argument('-P', '--copy-file', action='store_true', dest='cp',
            help='Copy source code file to output directory.')
    parser.add_argument('-o', '--output',
            type=str, dest='output', default=os.path.abspath('./'),
            help='Customize the output directory. (default is "./")')
    parser.add_argument('-f', '--database', metavar='<compile_commands.json>',
            type=str, dest='input', default=os.path.abspath('./compile_commands.json'),
            help='Customize the compilation database file.')
    parser.add_argument('-c', '--cc',
            type=str, dest='cc', default=Default.cc,
            help='Customize the C compiler. (default is clang)')
    parser.add_argument('-C', '--cxx',
            type=str, dest='cxx', default=Default.cxx,
            help='Customize the C++ compiler. (default is clang++)')
    parser.add_argument('-m', '--cfm',
            type=str, dest='cfm', default=Default.cfm,
            help='Customize the function mapping scanner. (default is clang-func-mapping)')
    parser.add_argument('-p', '--clang-path', metavar='CLANG_PATH', type=str, dest='clang',
            help='Customize the Clang executable directory for searching compilers.')
    parser.add_argument('-j', '--jobs', type=int, dest='jobs', default=1,
            help='Customize the number of jobs allowed in parallel.')
    parser.add_argument('--dump-only', action='store_true', dest='dump_only',
            help='Generate and dump commands to stdout only.')
    parser.add_argument('--ctu', action='store_true', dest='ctu',
            help='Alias to -M -A -L.')
    opts = parser.parse_args(args[1:])

    if opts.clang:
        if Default.cc == opts.cc:
            opts.cc = os.path.abspath(os.path.join(opts.clang, Default.cc))
        if Default.cxx == opts.cxx:
            opts.cxx = os.path.abspath(os.path.join(opts.clang, Default.cxx))
        if Default.cfm == opts.cfm:
            opts.cfm = os.path.abspath(os.path.join(opts.clang, Default.cfm))

    if opts.ctu:
        opts.fm = True
        opts.ast = True
        opts.ls = True

    return opts

    # }}}


# GetSourceFile: find out source file path through command object
#
#   command: a compile command object in database
def GetSourceFile(command):
    return os.path.abspath(os.path.join(command['directory'], command['file']))


# MakeCommand: replace the arguments with correct value for preprocess
#
#   opts: opts object (refer to ParseArguments)
#   command: the command object parsed from JSON
#   extension: the suffix representing its file type
#   prefix, suffix: the additional arguments to do the corresponding preprocess
#   argfilter: function to filter arguments
#
#   return: command object
#       the command object is defined as follows:
#           - arguments: list of arguments to be executed by compiler
#           - directory: compiler working directory
#           - output: directory of -o parameter
def MakeCommand(opts, command, extension, prefix, suffix, argfilter):
    # GenerateCompiler: generate the preprocessor compiler
    def GenerateCompiler(compiler):
        # check suffix only as the compiler argument can be full path
        if 'cc' == compiler[-2:]:
            return opts.cc
        elif 'c++' == compiler[-3:]:
            return opts.cxx
        else:
            assert False, 'What is this compiler? ' + compiler
    arguments = [GenerateCompiler(command['arguments'][0])]

    # append additional arguments for generating targets
    arguments += prefix

    # generate arguments (including the source file)
    # FIXME: when generating with both source files and object files,
    #        if object files are not available, clang will report 404.
    #        Currently, a filter is added to remove all .o or .obj files.
    arguments += argfilter(command['arguments'][1:])

    # generate the full path of output file with file type extension
    output = os.path.join(opts.output, GetSourceFile(command)[1:]) + '.' + extension
    arguments += ['-o', output]

    # append additional arguments for generating targets
    arguments += suffix

    return {'directory': command['directory'],
            'arguments': arguments,
            'output': output}


# MakeCopyCommand: make command for copy operation.
#
#   opts: opts object (refer to ParseArguments)
#   command: the command object parsed from JSON
#
#   return: command object of cp $file $output/$directory/$file
def MakeCopyCommand(opts, command):
    src = GetSourceFile(command)
    output = os.path.join(opts.output, src[1:])

    return {'directory': command['directory'],
            'arguments': ['cp', src, output],
            'output': output}


# RunCommand: run the command to do the preprocess
#
#   command: the command object to be executed. (in the parsed JSON format)
#   verbose: dump the command to be executed.
#   dump_only: dump and exit, do not execute.
def RunCommand(command, verbose, dump_only):
    if not dump_only:
        print('Generating "' + command['output'] + '"')

    arguments = command['arguments']
    outputDir = os.path.dirname(command['output'])

    if dump_only:
        print("mkdir -p " + outputDir)
        print("cd " + command['directory'])
        print(" \\\n\t".join(arguments))
        return
    elif verbose:
        print(arguments)

    # create directory for output file
    if not os.path.exists(outputDir):
        try:
            os.makedirs(outputDir)
        except FileExistsError:  # may happen when multi-thread
            pass

    process = popen(arguments, cwd=command['directory'])
    process.wait()


# GenerateFunctionMappingList: invoke clang-func-mapping to
#   generate externalFnMap.txt
#
#   opts: opts object (refer to ParseArguments)
#   jobs: the compilation database
def GenerateFunctionMappingList(opts, jobs):
    if not opts.dump_only:
        print('Generating function mapping list.')

    src = [GetSourceFile(i) for i in jobs]
    path = os.path.dirname(opts.input)
    arguments = [opts.cfm, '-p', path] + src
    outfile = os.path.join(opts.output, Default.fmname)

    if opts.dump_only:
        print(" \\\n\t".join(arguments) + " | \\\n" +
                "\tsed 's/$/.ast/g' >" + outfile)
        return

    process = popen(arguments, stdout=pipe, stderr=pipe)
    (out, err) = process.communicate()
    fm = out.decode('utf-8').replace('\n', '.ast\n')

    with open(outfile, 'w') as fout:
        fout.write(fm)

    process.wait()


# GenerateSourceFileList: dump all TU to an index file.
#   NOTE: Do nothing when dump_only.
#
#   opts: opts object (refer to ParseArguments)
#   jobs: the compilation database
def GenerateSourceFileList(opts, jobs):
    if opts.dump_only:
        return

    print('Generating {}.'.format(Default.si))

    with open(Default.srcidx, 'w') as fout:
        for i in jobs:
            fout.write(os.path.abspath(os.path.join(i['directory'], i['file'])))
            fout.write('\n')


# PreprocessProject: monitor and control the process of preprocess
#
#   opts: opts object (refer to ParseArguments)
def PreprocessProject(opts):
    def jobRun(opts, job):  # {{{
        commands = []

        # compile filter regexp and return a filter of it
        #   filterstr: a list of filter strings
        def getArgFilter(filterstr):  # {{{
            # create filter
            filters = []

            for fs in filterstr:
                if ':' == fs[-1]:
                    filters.append((re.compile(fs[:-1]), True))
                else:
                    filters.append((re.compile(fs), False))

            def ArgFilter(argv):
                ret = []

                I = iter(argv)
                while True:
                    A = next(I, None)
                    if A is None:
                        break

                    for f in filters:
                        # remove matched
                        if f[0].fullmatch(A):
                            if f[1]:
                                next(I)
                            A = None
                            break

                    if A:
                        ret.append(A)

                return ret

            return ArgFilter
            # }}}

        # jobRun:
        if opts.ast:
            commands.append(MakeCommand(
                opts, job, 'ast', ['-emit-ast'], ['-w'],
                getArgFilter(Default.filterstr)))

        if opts.i:
            commands.append(MakeCommand(
                opts, job, 'i', ['-E'], ['-w'],
                getArgFilter(Default.filterstr)))

        if opts.ll:
            commands.append(MakeCommand(
                opts, job, 'll', ['-c', '-g', '-emit-llvm', '-S'], ['-w'],
                getArgFilter(Default.filterstr)))

        if opts.bc:
            commands.append(MakeCommand(
                opts, job, 'bc', ['-c', '-g', '-emit-llvm'], ['-w'],
                getArgFilter(Default.filterstr)))

        if opts.cp:
            commands.append(MakeCopyCommand(opts, job))

        for cmd in commands:
            RunCommand(cmd, opts.verbose, opts.dump_only)

        # }}}

    # PreprocessProject:
    if not os.path.exists(opts.output):
        os.makedirs(opts.output)

    jobList = json.load(open(opts.input, 'r'))

    # Do sequential job:
    # Generate function mapping list
    if opts.fm:
        GenerateFunctionMappingList(opts, jobList)

    # Generate source file list
    if opts.ls:
        GenerateSourceFileList(opts, jobList)

    # Do parallel job:
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
