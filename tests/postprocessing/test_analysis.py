# -*- coding: utf-8 -*-

# BCDI: tools for pre(post)-processing Bragg coherent X-ray diffraction imaging data
#   (c) 07/2017-06/2019 : CNRS UMR 7344 IM2NP
#   (c) 07/2019-05/2021 : DESY PHOTON SCIENCE
#       authors:
#         Jerome Carnis, carnis_jerome@yahoo.fr
import os.path
import tempfile
import unittest
from copy import deepcopy
from logging import Logger
from pathlib import Path
from unittest.mock import patch

import matplotlib
import numpy as np

import bcdi.postprocessing.analysis as analysis
from bcdi.experiment.setup import Setup
from bcdi.postprocessing.postprocessing_runner import initialize_parameters
from bcdi.utils.parser import ConfigParser
from tests.config import run_tests

here = Path(__file__).parent
THIS_DIR = str(here)
CONFIG = str(here.parents[1] / "bcdi/examples/S11_config_postprocessing.yml")
parameters = initialize_parameters(ConfigParser(CONFIG).load_arguments())
parameters.update({"backend": "agg"})
matplotlib.use(parameters["backend"])


class TestAnalysis(unittest.TestCase):
    @patch("bcdi.postprocessing.analysis.Analysis.__abstractmethods__", set())
    def setUp(self) -> None:
        self.file_path = str(
            here.parents[1] / "bcdi/examples/S11_modes_252_420_392_prebinning_1_1_1.h5"
        )
        if not Path(parameters["root_folder"]).is_dir():
            self.skipTest(
                reason="This test can only run locally with the example dataset"
            )
        scan_index = 0
        self.parameters = parameters
        self.parameters.update(
            {
                "phasing_binning": [2, 2, 1],
                "reconstruction_files": [self.file_path],
            }
        )
        self.setup = Setup(
            beamline_name=self.parameters["beamline"],
            energy=self.parameters["energy"],
            outofplane_angle=self.parameters["outofplane_angle"],
            inplane_angle=self.parameters["inplane_angle"],
            tilt_angle=self.parameters["tilt_angle"],
            rocking_angle=self.parameters["rocking_angle"],
            distance=self.parameters["detector_distance"],
            sample_offsets=self.parameters["sample_offsets"],
            actuators=self.parameters["actuators"],
            custom_scan=self.parameters["custom_scan"],
            custom_motors=self.parameters["custom_motors"],
            dirbeam_detector_angles=self.parameters["dirbeam_detector_angles"],
            direct_beam=self.parameters["direct_beam"],
            is_series=self.parameters["is_series"],
            detector_name=self.parameters["detector"],
            template_imagefile=self.parameters["template_imagefile"][scan_index],
            roi=self.parameters["roi_detector"],
            binning=self.parameters["phasing_binning"],
            preprocessing_binning=self.parameters["preprocessing_binning"],
            custom_pixelsize=self.parameters["custom_pixelsize"],
        )

        self.setup.init_paths(
            sample_name=self.parameters["sample_name"][scan_index],
            scan_number=self.parameters["scans"][scan_index],
            root_folder=self.parameters["root_folder"],
            data_dir=self.parameters["data_dir"][scan_index],
            save_dir=self.parameters["save_dir"][scan_index],
            specfile_name=self.parameters["specfile_name"][scan_index],
            template_imagefile=self.parameters["template_imagefile"][scan_index],
        )
        self.setup.create_logfile(
            scan_number=self.parameters["scans"][scan_index],
            root_folder=self.parameters["root_folder"],
            filename=self.setup.detector.specfile,
        )
        self.setup.read_logfile(scan_number=self.parameters["scans"][scan_index])
        self.process = analysis.Analysis(
            scan_index=0,
            parameters=self.parameters,
            setup=self.setup,
        )

    def test_instantiation(self):
        self.assertEqual(self.process.scan_index, 0)
        self.assertIsInstance(self.process.parameters, dict)
        self.assertIsInstance(self.process.logger, Logger)
        self.assertIsInstance(self.process.setup, Setup)
        self.assertEqual(self.process.nb_reconstructions, 1)
        self.assertEqual(self.process.file_path[0], self.file_path)
        self.assertIsInstance(self.process.comment, analysis.Comment)
        self.assertEqual(self.process.comment.text, "_mode")
        self.assertIsNone(self.process.extent_phase)

    @patch("bcdi.postprocessing.analysis.Analysis.__abstractmethods__", set())
    def test_negative_scan_index(self):
        with self.assertRaises(ValueError):
            analysis.Analysis(
                scan_index=-1,
                parameters=self.parameters,
                setup=self.setup,
            )

    def test_get_shape_during_phasing(self):
        expected = [126, 210, 392]
        print(self.process.original_shape)
        self.assertTrue(
            all(
                val1 == val2
                for val1, val2 in zip(self.process.original_shape, expected)
            )
        )

    @patch("bcdi.postprocessing.analysis.Analysis.__abstractmethods__", set())
    def test_crop_pad_data(self):
        new_params = deepcopy(self.parameters)
        new_params.update({"original_size": [20, 30, 40]})
        expected = [10, 15, 40]
        process = analysis.Analysis(
            scan_index=0,
            parameters=new_params,
            setup=self.setup,
        )
        process.crop_pad_data(process.original_shape)
        self.assertTrue(
            all(val1 == val2 for val1, val2 in zip(process.data.shape, expected))
        )

    @patch("bcdi.postprocessing.analysis.Analysis.__abstractmethods__", set())
    def test_find_data_range(self):
        process = analysis.Analysis(
            scan_index=0,
            parameters=self.parameters,
            setup=self.setup,
        )
        expected = (86, 118, 122)
        process.find_data_range(amplitude_threshold=0.05, plot_margin=0)
        self.assertTrue(
            all(val1 == val2 for val1, val2 in zip(process.optimized_range, expected))
        )

    def test_find_best_reconstruction(self):
        expected = 0
        self.process.find_best_reconstruction()
        self.assertIsInstance(self.process.sorted_reconstructions_best_first, list)
        self.assertEqual(self.process.sorted_reconstructions_best_first[0], expected)

    def test_average_reconstructions(self):
        self.process.average_reconstructions()

    def test_get_phase_manipulator(self):
        self.assertIsInstance(
            self.process.get_phase_manipulator(), analysis.PhaseManipulator
        )

    def test_update_data(self):
        shape = self.process.data.shape
        self.process.update_data(modulus=np.zeros(shape), phase=np.zeros(shape))
        self.assertTrue(np.allclose(self.process.data, 0.0))

    def test_center_object_based_on_modulus(self):
        self.process.center_object_based_on_modulus()

    def test_save_modulus_phase(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            self.process.save_modulus_phase(tmpdir + "/amp_phase")
            self.assertTrue(os.path.isfile(f"{tmpdir}/amp_phase.npz"))

    def test_save_support(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            self.process.save_support(tmpdir + "/support")
            self.assertTrue(os.path.isfile(f"{tmpdir}/support.npz"))

    def test_save_to_vti(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            self.process.parameters.update({"tilt_angle": 0.1})
            self.process.save_to_vti(tmpdir + "/test.vti")
            self.assertTrue(os.path.isfile(f"{tmpdir}/test.vti"))
            self.process.parameters.update({"tilt_angle": None})

    def test_detector_angles_correction_needed(self):
        self.assertTrue(self.process.detector_angles_correction_needed)

    def test_bragg_peak_is_retrievable(self):
        self.assertTrue(self.process.undefined_bragg_peak_but_retrievable)

    def test_update_parameters(self):
        expected = [127, 214, 317]
        output = self.process.retrieve_bragg_peak()
        self.process.update_parameters({"bragg_peak": output["bragg_peak"]})
        self.assertTrue(
            all(
                val1 == val2
                for val1, val2 in zip(expected, self.process.parameters["bragg_peak"])
            )
        )
        self.process.update_parameters({"bragg_peak": None})

    def test_update_detector_angles(self):
        bragg_peak = [127, 214, 317]
        expected_inplane = 0.4864306733991417
        expected_outofplane = 35.36269069963432
        self.process.update_detector_angles(bragg_peak)
        self.assertAlmostEqual(self.process.setup.inplane_angle, expected_inplane)
        self.assertAlmostEqual(self.process.setup.outofplane_angle, expected_outofplane)

    def test_get_interplanar_distance(self):
        expected = 2.2637604819304933
        self.assertAlmostEqual(self.process.get_interplanar_distance, expected)

    def test_get_q_bragg_laboratory_frame(self):
        expected = [-0.84449687, 2.64216636, -0.09732299]
        self.assertTrue(
            np.allclose(self.process.get_q_bragg_laboratory_frame, expected)
        )

    def test_get_normalized_q_bragg_laboratory_frame(self):
        expected = [-0.30426266, 0.95194261, -0.03506437]
        self.assertTrue(
            np.allclose(self.process.get_normalized_q_bragg_laboratory_frame, expected)
        )

    def test_get_norm_q_bragg(self):
        expected = 2.7755521652279227
        self.assertAlmostEqual(self.process.get_norm_q_bragg, expected)


class TestPhaseManipulator(unittest.TestCase):
    def setUp(self) -> None:
        self.shape = (6, 6, 6)
        self.phase_manipulator = analysis.PhaseManipulator(
            data=np.ones(self.shape),
            parameters=deepcopy(parameters),
            original_shape=parameters["original_size"],
        )

    def test_instantiation(self):
        self.assertIsNone(self.phase_manipulator.extent_phase)
        self.assertIsNone(self.phase_manipulator.phase_ramp)
        self.assertIsInstance(self.phase_manipulator.modulus, np.ndarray)
        self.assertIsInstance(self.phase_manipulator.phase, np.ndarray)
        self.assertIsNone(self.phase_manipulator.save_directory)

    def test_remove_ramp(self):
        self.phase_manipulator.remove_ramp()
        self.assertIsInstance(self.phase_manipulator.phase_ramp, list)
        self.assertTrue(np.allclose(self.phase_manipulator.phase_ramp, 0))

    def test_plot_phase(self):
        plot_title = "test"
        with tempfile.TemporaryDirectory() as tmpdir:
            self.phase_manipulator.save_directory = tmpdir
            self.phase_manipulator.plot_phase(plot_title, save_plot=True)
            self.assertTrue(os.path.isfile(f"{tmpdir}/{plot_title}.png"))

    def test_center_phase_none(self):
        with self.assertRaises(ValueError):
            self.phase_manipulator.center_phase()

    def test_phase_offset_removel(self):
        self.phase_manipulator.remove_offset()

    def test_average_phase(self):
        self.phase_manipulator.parameters["half_width_avg_phase"] = 2
        self.phase_manipulator.average_phase()

    def test_add_ramp_none(self):
        with self.assertRaises(ValueError):
            self.phase_manipulator.add_ramp()

    def test_add_ramp_sign_positive(self):
        self.phase_manipulator._phase_ramp = [1, 1, 1]
        self.phase_manipulator.add_ramp(sign=1)
        self.assertAlmostEqual(self.phase_manipulator.phase.min(), 0)
        self.assertAlmostEqual(self.phase_manipulator.phase.max(), 15)

    def test_add_ramp_sign_negative(self):
        self.phase_manipulator._phase_ramp = [1, 1, 1]
        self.phase_manipulator.add_ramp(sign=-1)
        self.assertAlmostEqual(self.phase_manipulator.phase.min(), -15)
        self.assertAlmostEqual(self.phase_manipulator.phase.max(), 0)

    def test_apodize(self):
        self.phase_manipulator.apodize()


class TestCreateAnalysis(unittest.TestCase):
    def setUp(self) -> None:
        self.file_path = str(
            here.parents[1] / "bcdi/examples/S11_modes_252_420_392_prebinning_1_1_1.h5"
        )
        if not Path(parameters["root_folder"]).is_dir():
            self.skipTest(
                reason="This test can only run locally with the example dataset"
            )
        self.parameters = parameters
        self.parameters.update(
            {
                "reconstruction_files": [self.file_path],
            }
        )
        self.setup = Setup(
            beamline_name=self.parameters["beamline"],
            binning=self.parameters["phasing_binning"],
        )

    def test_create_analysis_linearization(self):
        self.assertIsInstance(
            analysis.create_analysis(
                scan_index=0,
                parameters=self.parameters,
                setup=self.setup,
            ),
            analysis.DetectorFrameLinearization,
        )

    def test_create_analysis_already_orthogonal(self):
        param_dict = deepcopy(self.parameters)
        param_dict["data_frame"] = "crystal"
        self.assertIsInstance(
            analysis.create_analysis(
                scan_index=0,
                parameters=param_dict,
                setup=self.setup,
            ),
            analysis.OrthogonalFrame,
        )

    def test_define_analysis_type(self):
        self.assertEqual(
            analysis.define_analysis_type(
                data_frame=parameters["data_frame"],
                interpolation_method=parameters["interpolation_method"],
            ),
            "linearization",
        )


class TestDetectorFrameLinearization(unittest.TestCase):
    def setUp(self) -> None:
        self.file_path = str(
            here.parents[1] / "bcdi/examples/S11_modes_252_420_392_prebinning_1_1_1.h5"
        )
        if not Path(parameters["root_folder"]).is_dir():
            self.skipTest(
                reason="This test can only run locally with the example dataset"
            )
        self.parameters = parameters
        self.parameters.update(
            {
                "reconstruction_files": [self.file_path],
            }
        )
        self.setup = Setup(
            beamline_name=self.parameters["beamline"],
            binning=self.parameters["phasing_binning"],
        )
        self.analysis = analysis.create_analysis(
            name="linearization",
            scan_index=0,
            parameters=self.parameters,
            setup=self.setup,
        )

    def test_interpolate_into_crystal_frame(self):
        with self.assertRaises(ValueError):
            self.analysis.interpolate_into_crystal_frame()


if __name__ == "__main__":
    run_tests(TestAnalysis)
    run_tests(TestPhaseManipulator)
    run_tests(TestCreateAnalysis)
    run_tests(TestDetectorFrameLinearization)
