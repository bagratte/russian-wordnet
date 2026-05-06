#!/usr/bin/env python3

import os
import shutil
import tempfile
import unittest

import ruwordnet
import wn
import wn.lmf
import wn.validate

XML_FILE = 'russian-wordnet-2021.xml'


@unittest.skipUnless(os.path.exists(XML_FILE), f'{XML_FILE} not found — run main.py first')
class TestRuWordNetLMF(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.mkdtemp()
        cls._orig_data_dir = wn.config.data_directory
        wn.config.data_directory = cls._tmp
        wn.add(XML_FILE, progress_handler=None)

    @classmethod
    def tearDownClass(cls):
        wn.config.data_directory = cls._orig_data_dir
        shutil.rmtree(cls._tmp, ignore_errors=True)

    def test_lexicon_loaded(self):
        lexicons = wn.lexicons()
        self.assertEqual(len(lexicons), 1)
        self.assertEqual(lexicons[0].id, 'ruwn')

    def test_language_is_russian(self):
        ru_lexicons = wn.lexicons(lang='ru')
        self.assertEqual(len(ru_lexicons), 1)
        self.assertEqual(ru_lexicons[0].language, 'ru')

    def test_synset_count_matches_ruwordnet(self):
        ruwn = ruwordnet.RuWordNet()
        self.assertEqual(len(wn.synsets()), len(ruwn.synsets))

    def test_sense_count_matches_ruwordnet(self):
        ruwn = ruwordnet.RuWordNet()
        self.assertEqual(len(wn.senses()), len(ruwn.senses))

    def test_no_validation_errors(self):
        resource = wn.lmf.load(XML_FILE, progress_handler=None)
        lex = resource['lexicons'][0]
        report = wn.validate.validate(lex, select=['E', 'W'], progress_handler=None)
        for code, check in report.items():
            if check['items']:
                print(f'{code} ({check["message"]}): {len(check["items"])} issue(s)')
        errors = {code: check for code, check in report.items() if check['items'] and code.startswith('E')}
        self.assertFalse(errors, errors)


if __name__ == '__main__':
    unittest.main()
