"""
.. module:: gatk
   :platform: Unix, OSX
   :synopsis: A wrapper module for calling GATK utilities.

.. moduleauthor:: Daniel Gaston <daniel.gaston@gmail.com>


"""

__author__ = 'dgaston'

import sys
import multiprocessing

from ngsflow.utils import utilities
from ngsflow import pipeline


def diagnosetargets(job, config, sample, input_bam):
    """Run GATK's DiagnoseTargets against the supplied region

    :param config: The configuration dictionary.
    :type config: dict.
    :param sample: sample name.
    :type sample: str.
    :param input_bam: The input_bam file name to process.
    :type input_bam: str.
    :returns:  str -- The DiagnoseTargets output vcf file name.

    """

    diagnose_targets_vcf = "{}.diagnosetargets.vcf".format(sample)
    missing_intervals = "{}.missing.intervals".format(sample)
    logfile = "{}.diagnose_targets.log".format(sample)

    command = ("java",
               "-Xmx{}g".format(2),
               "-jar",
               "{}".format(config['gatk']['bin']),
               "-T",
               "DiagnoseTargets",
               "-R",
               "{}".format(config['reference']),
               "-L",
               "{}".format(config['regions']),
               "--coverage_status_threshold",
               "{}".format(config['coverage_loci_threshold']),
               "--bad_mate_status_threshold",
               "{}".format(config['bad_mate_threshold']),
               "--minimum_coverage",
               "{}".format(config['coverage_threshold']),
               "--quality_status_threshold",
               "{}".format(config['quality_loci_threshold']),
               "-I",
               "{}".format(input_bam),
               "-o",
               "{}".format(diagnose_targets_vcf),
               "--missing_intervals",
               "{}".format(missing_intervals))

    job.fileStore.logToMaster("GATK DiagnoseTargets Command: {}\n".format(command))
    pipeline.run_and_log_command(" ".join(command), logfile)

    return diagnose_targets_vcf


def annotate_vcf(job, config, sample, input_vcf, input_bam, num_threads):
    """Run GATK's VariantAnnotation on the specified VCF

    :param config: The configuration dictionary.
    :type config: dict.
    :param sample: sample name.
    :type sample: str.
    :param input_vcf: The input_vcf file name to process.
    :type input_vcf: str.
    :param input_bam: The input_bam file name to process.
    :type input_bam: str.
    :param num_threads: Number of threads for local processing.
    :type num_threads: int.
    :returns:  str -- The output vcf file name.

    """

    output_vcf = "{}.annotated.vcf".format(sample)
    annotation_logfile = "{}.variantannotation.log".format(sample)

    annotation_command = ("java",
                          "-Xmx{}g".format(config['gatk']['max_mem']),
                          "-jar",
                          "{}".format(config['gatk']['bin']),
                          "-T",
                          "VariantAnnotator",
                          "-R",
                          "{}".format(config['reference']),
                          "-nt",
                          "{}".format(num_threads),
                          "--group",
                          "StandardAnnotation",
                          "--dbsnp",
                          "{}".format(config['dbsnp']),
                          "-I",
                          "{}".format(input_bam),
                          "--variant",
                          "{}".format(input_vcf),
                          "-L",
                          "{}".format(input_vcf),
                          "-o",
                          "{}".format(output_vcf))

    job.fileStore.logToMaster("GATK VariantAnnotator Command: {}\n".format(annotation_command))
    pipeline.run_and_log_command(" ".join(annotation_command), annotation_logfile)

    return output_vcf


def filter_variants(job, config, sample, input_vcf):
    """Run GATK's VariantFilter on the specified VCF

    :param config: The configuration dictionary.
    :type config: dict.
    :param sample: sample name.
    :type sample: str.
    :param input_vcf: The input_vcf file name to process.
    :type input_vcf: str.
    :returns:  str -- The output vcf file name.

    """

    output_vcf = "{}.filtered.vcf".format(sample)
    filter_log = "{}.variantfiltration.log".format(sample)

    filter_command = ("java",
                      "-Xmx{}g".format(config['gatk']['max_mem']),
                      "-jar",
                      "{}".format(config['gatk']['bin']),
                      "-T",
                      "VariantFiltration",
                      "-R",
                      "{}".format(config['reference']),
                      "--filterExpression",
                      "'MQ0 > 50'",
                      "--filterName",
                      "'HighMQ0'",
                      "--filterExpression",
                      "'DP < {}'".format(config['coverage_threshold']),
                      "--filterName",
                      "'LowDepth'",
                      "--filterExpression",
                      "'QUAL < 10'",
                      "--filterName",
                      "'LowQual'",
                      "--filterExpression",
                      "'MQ < 10'",
                      "--filterName",
                      "'LowMappingQual'",
                      "--variant",
                      "{}".format(input_vcf),
                      "-o",
                      "{}".format(output_vcf))

    job.fileStore.logToMaster("GATK VariantFiltration Command: {}\n".format(filter_command))
    pipeline.run_and_log_command(" ".join(filter_command), filter_log)

    return output_vcf


def run_mark_duplicates(project_config, sample_config, tool_config, resource_config):
    """Run Picard MarkDuplicates"""

    sys.stdout.write("Running MarkDuplicates\n")
    instructions = list()
    for sample in sample_config:
        logfile = "%s.markduplicates.log" % sample['name']

        try:
            sample['sorted_bam'] = sample['bam']
        except KeyError:
            pass

        sample['dedup_bam'] = "%s.dedup.sorted.bam" % sample['name']
        metrics = "%s.dedup.metrics" % sample['name']

        command = ("java -Xmx%sg -jar %s MarkDuplicates CREATE_INDEX=true INPUT=%s OUTPUT=%s METRICS_FILE=%s "
                   "VALIDATION_STRINGENCY=LENIENT" %
                   (tool_config['gatk']['max_mem'], tool_config['picard']['bin'], sample['working_bam'],
                    sample['dedup_bam'], metrics))
        instructions.append((command, logfile))
        sample['working_bam'] = sample['dedup_bam']


def add_or_replace_readgroups(job, config, sample, input_bam):
    """Run Picard's AddOrReplaceReadGroups on the specified BAM

    :param config: The configuration dictionary.
    :type config: dict.
    :param sample: sample name.
    :type sample: str.
    :param input_bam: The input_bam file name to process.
    :type input_bam: str.
    :returns:  str -- The output bam file name.

    """

    job.fileStore.logToMaster("Running AddOrReplaceReadGroups in sample: {}".format(sample))

    output_bam = "{}.rg.sorted.bam".format(sample)
    logfile = "{}.addreadgroups.log".format(sample)
    index_log = "{}.buildindex.log".format(sample)

    command = ("java",
               "-Xmx{}g".format(config['gatk']['max_mem']),
               "-jar",
               "{}".format(config['picard']),
               "AddOrReplaceReadGroups",
               "INPUT={}".format(input_bam),
               "OUTPUT={}".format(output_bam),
               "RGID={}".format(sample),
               "RGSM={}".format(sample),
               "RGLB={}".format(sample),
               "RGPL=illumina",
               "RGPU=miseq")

    command2 = ("java",
                "-Xmx{}g".format(config['gatk']['max_mem']),
                "-jar",
                "{}".format(config['picard']),
                "BuildBamIndex",
                "INPUT={}".format(output_bam))

    job.fileStore.logToMaster("GATK AddOrReplaceReadGroupsCommand Command: {}\n".format(command))
    pipeline.run_and_log_command(" ".join(command), logfile)

    job.fileStore.logToMaster("GATK BuildBamIndex Command: {}\n".format(command2))
    pipeline.run_and_log_command(" ".join(command2), index_log)

    return output_bam


def realign_target_creator(job, config, sample, input_bam):
    """Run GATK TargetCreator on the specified BAM to identify targets for realignment

    :param config: The configuration dictionary.
    :type config: dict.
    :param sample: sample name.
    :type sample: str.
    :param input_bam: The input_bam file name to process.
    :type input_bam: str.
    :returns:  str -- The file name of the targets file.

    """

    targets = "{}.targets.intervals".format(sample)
    targets_log = "{}.targetcreation.log".format(sample)

    command = ("java",
               "-Xmx{}g".format(config['gatk']['max_mem']),
               "-jar",
               "{}".format(config['gatk']),
               "-T",
               "IndelRealigner",
               "-R",
               "{}".format(config['reference']),
               "-I",
               "{}".format(input_bam),
               "-o",
               "{}".format(targets),
               "-known",
               "{}".format(config['indel1']),
               "-known",
               "{}".format(config['indel2']),
               "-targetIntervals",
               "{}".format(targets),
               "--read_filter",
               "NotPrimaryAlignment")

    job.fileStore.logToMaster("GATK RealignerTargetCreator Command: {}\n".format(command))
    pipeline.run_and_log_command(" ".join(command), targets_log)

    return targets


def realign_indels(job, config, sample, input_bam, targets):
    """Run GATK Indel Realignment on the specified BAM

    :param config: The configuration dictionary.
    :type config: dict.
    :param sample: sample name.
    :type sample: str.
    :param input_bam: The input_bam file name to process.
    :type input_bam: str.
    :param targets: The file name of targets to realign.
    :type targets: str.
    :returns:  str -- The output bam file name.

    """

    output_bam = "{}.realigned.sorted.bam".format(sample)
    realign_log = "{}.realignindels.log".format(sample)

    command = ("java",
               "-Xmx{}g".format(config['gatk']['max_mem']),
               "-jar",
               "{}".format(config['gatk']),
               "-T",
               "RealignerTargetCreator",
               "-R",
               "{}".format(config['reference']),
               "-I",
               "{}".format(input_bam),
               "-o",
               "{}".format(targets),
               "-known",
               "{}".format(config['indel1']),
               "-known",
               "{}".format(config['indel2']),
               "-nt",
               "{}".format(multiprocessing.cpu_count()))

    job.fileStore.logToMaster("GATK IndelRealigner Command: {}\n".format(command))
    utilities.touch("{}".format(output_bam))
    pipeline.run_and_log_command(" ".join(command), realign_log)

    return output_bam


def recalibrator(job, config, sample, input_bam):
    """Run GATK Recalibrator on the specified BAM

    :param config: The configuration dictionary.
    :type config: dict.
    :param sample: sample name.
    :type sample: str.
    :param input_bam: The input_bam file name to process.
    :type input_bam: str.
    :returns:  str -- The output bam file name.

    """

    output_bam = "{}.recalibrated.sorted.bam".format(sample)
    recal_config = "{}.recal".format(sample)
    recal_log = "{}.recalibrate.log".format(sample)
    print_log = "{}.printrecalibrated.log".format(sample)
    cp_log = "{}.copy.log".format(sample)

    # Calculate covariates
    recal_commands = ("java",
                      "-Xmx{}g".format(config['gatk']['max_mem']),
                      "-jar",
                      "{}".format(config['gatk']),
                      "-T",
                      "BaseRecalibrator",
                      "-R",
                      "{}".format(config['reference']),
                      "-I",
                      "{}".format(input_bam),
                      "-o",
                      "{}".format(recal_config),
                      "--knownSites",
                      "{}".format(config['dbsnp']),
                      "-nct",
                      "{}".format(multiprocessing.cpu_count()))

    # Print recalibrated BAM
    print_reads_command = ("java",
                           "-Xmx{}g".format(config['gatk']['max_mem']),
                           "-jar",
                           "{}".format(config['gatk']),
                           "-T",
                           "PrintReads",
                           "-R",
                           "{}".format(config['reference']),
                           "-I",
                           "{}".format(input_bam),
                           "-o",
                           "{}".format(output_bam),
                           "-BQSR",
                           "{}".format(recal_config),
                           "-nct",
                           "{}".format(multiprocessing.cpu_count()))

    # Copy index to alternative name
    cp_command = ("cp",
                  "{}.recalibrated.sorted.bai".format(sample),
                  "{}.recalibrated.sorted.bam.bai".format(sample))

    job.fileStore.logToMaster("GATK BaseRecalibrator Command: {}\n".format(recal_commands))
    pipeline.run_and_log_command(" ".join(recal_commands), recal_log)

    job.fileStore.logToMaster("GATK PrintReads Command: {}\n".format(print_reads_command))
    pipeline.run_and_log_command(" ".join(print_reads_command), print_log)

    job.fileStore.logToMaster("GATK Copy Command: {}\n".format(cp_command))
    pipeline.run_and_log_command(" ".join(cp_command), cp_log)

    return output_bam
