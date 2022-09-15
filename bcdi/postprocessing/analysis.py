# -*- coding: utf-8 -*-

# BCDI: tools for pre(post)-processing Bragg coherent X-ray diffraction imaging data
#   (c) 07/2017-06/2019 : CNRS UMR 7344 IM2NP
#   (c) 07/2019-05/2021 : DESY PHOTON SCIENCE
#       authors:
#         Jerome Carnis, carnis_jerome@yahoo.fr
"""Implementation of the analysis classes."""

import logging
import os
import tkinter as tk
from abc import ABC, abstractmethod
from tkinter import filedialog
from typing import Any, Dict, List, Optional, Tuple, Union

import numpy as np

import bcdi.graph.graph_utils as gu
import bcdi.postprocessing.postprocessing_utils as pu
import bcdi.preprocessing.bcdi_utils as bu
import bcdi.utils.image_registration as reg
import bcdi.utils.utilities as util
import bcdi.utils.validation as valid
from bcdi.experiment.setup import Setup
from bcdi.utils.constants import AXIS_TO_ARRAY
from bcdi.utils.text import Comment

module_logger = logging.getLogger(__name__)


class Analysis(ABC):
    """Base class for the post-processing analysis workflow."""

    def __init__(
        self,
        scan_index: int,
        parameters: Dict[str, Any],
        setup: Setup,
        **kwargs,
    ) -> None:
        self.scan_index = scan_index
        self.parameters = parameters
        self.setup = setup
        self.logger = kwargs.get("logger", module_logger)

        self.file_path = self.get_reconstrutions_path()
        self.data = self.load_reconstruction_data(file_index=0)
        self.original_shape = self.get_shape_during_phasing(
            self.parameters.get("original_size")
        )
        self.extent_phase: Optional[float] = None
        self.voxel_sizes: Optional[List[float]] = None
        self.optimized_range = self.original_shape
        self.sorted_reconstructions_best_first = [0]
        self.nb_reconstructions = len(self.file_path)
        self.comment = self.initialize_comment()
        if os.path.splitext(self.file_path[0])[1] == ".h5":
            self.comment.concatenate("mode")

    @property
    def undefined_bragg_peak_but_retrievable(self) -> bool:
        return (
            self.parameters["bragg_peak"] is None
            and self.setup.detector.template_imagefile is not None
        )

    @property
    def detector_angles_correction_needed(self) -> bool:
        return self.parameters["data_frame"] == "detector" and (
            not self.parameters["outofplane_angle"]
            or not self.parameters["inplane_angle"]
        )

    @property
    def get_interplanar_distance(self) -> float:
        return 2 * np.pi / np.linalg.norm(self.setup.q_laboratory)

    @property
    def get_normalized_q_bragg_laboratory_frame(self) -> List[float]:
        return self.setup.q_laboratory / np.linalg.norm(self.setup.q_laboratory)

    @property
    def get_norm_q_bragg(self) -> float:
        return np.linalg.norm(self.setup.q_laboratory)

    @property
    def get_q_bragg_laboratory_frame(self) -> List[float]:
        return self.setup.q_laboratory

    @property
    def scan_index(self) -> int:
        return self._scan_index

    @scan_index.setter
    def scan_index(self, val: int) -> None:
        if val < 0:
            raise ValueError("'scan_index' should be >= 0, " f"got {val}")
        self._scan_index = val

    def average_reconstructions(self) -> None:
        average_array = np.zeros(self.optimized_range)
        average_counter = 1
        self.logger.info(
            f"Averaging using {self.nb_reconstructions} " "candidate reconstructions"
        )
        for counter, value in enumerate(self.sorted_reconstructions_best_first):
            obj, extension = util.load_file(self.file_path[value])
            self.logger.info(f"Opening {self.file_path[value]}")
            self.parameters[f"from_file_{counter}"] = self.file_path[value]

            if self.parameters["flip_reconstruction"]:
                obj = pu.flip_reconstruction(
                    obj, debugging=True, cmap=self.parameters["colormap"].cmap
                )

            if extension == ".h5":  # data is already cropped by PyNX
                self.parameters["centering_method"]["direct_space"] = "skip"
                # correct a roll after the decomposition into modes in PyNX
                obj = np.roll(obj, self.parameters["roll_modes"], axis=(0, 1, 2))
                fig, _, _ = gu.multislices_plot(
                    abs(obj),
                    sum_frames=True,
                    plot_colorbar=True,
                    title="1st mode after centering",
                    cmap=self.parameters["colormap"].cmap,
                )

            # use the range of interest defined above
            obj = util.crop_pad(
                array=obj,
                output_shape=self.optimized_range,
                debugging=False,
                cmap=self.parameters["colormap"].cmap,
            )

            # align with average reconstruction
            if counter == 0:  # the fist array loaded will serve as reference object
                self.logger.info("This reconstruction will be used as reference.")
                self.data = obj

            average_array, flag_avg = reg.average_arrays(
                avg_obj=average_array,
                ref_obj=self.data,
                obj=obj,
                support_threshold=0.25,
                correlation_threshold=self.parameters["correlation_threshold"],
                aligning_option="dft",
                space=self.parameters["averaging_space"],
                reciprocal_space=False,
                is_orthogonal=self.parameters["is_orthogonal"],
                debugging=self.parameters["debug"],
                cmap=self.parameters["colormap"].cmap,
            )
            average_counter += flag_avg

        self.data = average_array / average_counter
        if average_counter > 1:
            self.logger.info(f"Average performed over {average_counter} arrays")

    def center_object_based_on_modulus(self):
        self.data = pu.center_object(
            method=self.parameters["centering_method"]["direct_space"], obj=self.data
        )

    def crop_pad_data(self, value: Tuple[int, ...]) -> None:
        self.data = util.crop_pad(
            array=self.data,
            output_shape=value,
            cmap=self.parameters["colormap"].cmap,
        )

    def find_best_reconstruction(self) -> None:
        if self.nb_reconstructions > 1:
            self.logger.info(
                "Trying to find the best reconstruction\nSorting by "
                f"{self.parameters['sort_method']}"
            )
            self.sorted_reconstructions_best_first = pu.sort_reconstruction(
                file_path=self.file_path,
                amplitude_threshold=self.parameters["isosurface_strain"],
                data_range=self.optimized_range,
                sort_method=self.parameters["sort_method"],
            )
        else:
            self.sorted_reconstructions_best_first = [0]

    def find_data_range(
        self, amplitude_threshold: float = 0.1, plot_margin: Union[int, List[int]] = 10
    ) -> None:
        self.optimized_range = pu.find_datarange(
            array=self.data,
            amplitude_threshold=amplitude_threshold,
            plot_margin=plot_margin,
            keep_size=self.parameters["keep_size"],
        )

        self.logger.info(
            "Data shape used for orthogonalization and plotting: "
            f"{self.optimized_range}"
        )

    def get_phase_manipulator(self):
        return PhaseManipulator(
            data=self.data,
            parameters=self.parameters,
            original_shape=self.original_shape,
            savedir=self.setup.detector.savedir,
            logger=self.logger,
        )

    def get_reconstrutions_path(self) -> Tuple[str]:
        if self.parameters["reconstruction_files"][self.scan_index] is not None:
            file_path = self.parameters["reconstruction_files"][self.scan_index]
            if isinstance(file_path, str):
                file_path = (file_path,)
        else:
            root = tk.Tk()
            root.withdraw()
            file_path = filedialog.askopenfilenames(
                initialdir=self.setup.detector.scandir
                if self.parameters["data_dir"] is None
                else self.setup.detector.datadir,
                filetypes=[
                    ("HDF5", "*.h5"),
                    ("CXI", "*.cxi"),
                    ("NPZ", "*.npz"),
                    ("NPY", "*.npy"),
                ],
            )
        return tuple(file_path)

    def get_shape_during_phasing(
        self, user_defined_shape: Optional[List[int]]
    ) -> Tuple[int, ...]:

        input_shape = (
            user_defined_shape if user_defined_shape is not None else self.data.shape
        )
        self.logger.info(
            f"FFT size before accounting for phasing_binning: {input_shape}"
        )
        original_shape = tuple(
            int(input_shape[index] // binning)
            for index, binning in enumerate(self.setup.detector.binning)
        )
        self.logger.info(f"Binning used during phasing: {self.setup.detector.binning}")
        self.logger.info(f"Original data shape during phasing: {original_shape}")
        return original_shape

    def initialize_comment(self) -> Comment:
        return Comment(self.parameters.get("comment", ""))

    @abstractmethod
    def interpolate_into_crystal_frame(self):
        """Interpolate the direct space object into the crystal frame.

        The exact steps depend on which frame the data lies in."""

    def load_diffraction_data(self) -> Tuple[np.ndarray, ...]:
        return self.setup.loader.load_check_dataset(
            scan_number=self.parameters["scans"][self.scan_index],
            setup=self.setup,
            frames_pattern=self.parameters["frames_pattern"],
            bin_during_loading=False,
            flatfield=self.parameters["flatfield_file"],
            hotpixels=self.parameters["hotpixels_file"],
            background=self.parameters["background_file"],
            normalize=self.parameters["normalize_flux"],
        )

    def load_reconstruction_data(self, file_index: int) -> np.ndarray:
        return util.load_file(self.file_path[file_index])[0]

    def retrieve_bragg_peak(self) -> Dict[str, Any]:
        output = self.load_diffraction_data()

        return bu.find_bragg(
            array=output[0],
            binning=None,
            roi=self.setup.detector.roi,
            peak_method=self.parameters["centering_method"]["reciprocal_space"],
            tilt_values=self.setup.tilt_angles,
            savedir=self.setup.detector.savedir,
            logger=self.logger,
            plot_fit=True,
        )

    def save_modulus_phase(self, filename: str) -> None:
        np.savez_compressed(
            filename,
            amp=abs(self.data),
            phase=np.angle(self.data),
        )

    def save_support(self, filename: str, modulus_threshold: float = 0.1) -> None:
        support = np.zeros(self.data.shape)
        support[abs(self.data) / abs(self.data).max() > modulus_threshold] = 1
        np.savez_compressed(filename, obj=support)

    def save_to_vti(self, filename: str) -> None:
        voxel_z, voxel_y, voxel_x = self.setup.voxel_sizes_detector(
            array_shape=self.original_shape,
            tilt_angle=(
                self.parameters["tilt_angle"]
                * self.setup.detector.preprocessing_binning[0]
                * self.setup.detector.binning[0]
            ),
            pixel_x=self.setup.detector.pixelsize_x,
            pixel_y=self.setup.detector.pixelsize_y,
            verbose=True,
        )
        # save raw amp & phase to VTK (in VTK, x is downstream, y vertical, z inboard)
        gu.save_to_vti(
            filename=filename,
            voxel_size=(voxel_z, voxel_y, voxel_x),
            tuple_array=(abs(self.data), np.angle(self.data)),
            tuple_fieldnames=("amp", "phase"),
            amplitude_threshold=0.01,
        )

    def update_data(self, modulus: np.ndarray, phase: np.ndarray) -> None:
        # here the phase is again wrapped in [-pi pi[
        self.data = modulus * np.exp(1j * phase)

    def update_detector_angles(self, bragg_peak_position: List[int]) -> None:
        self.setup.correct_detector_angles(bragg_peak_position=bragg_peak_position)

    def update_parameters(self, dictionary: Dict[str, Any]) -> None:
        self.parameters.update(dictionary)


class DetectorFrameLinearization(Analysis):
    """Analysis workflow for interpolation based on the linearization matrix.

    The data before interpolation is in the detector frame
    (axis 0 = rocking angle, axis 1 detector Y, axis 2 detector X).
    The data after interpolation is in the pseudo-crystal frame (only 'ref_axis_q'is
    an axis of the crystal frame, there is an unknown inplane rotation around it).
    """

    def interpolate_into_crystal_frame(self) -> None:
        """Interpolate the data in the pseudo crystal frame."""
        obj_ortho, voxel_sizes, transfer_matrix = self.setup.ortho_directspace(
            arrays=self.data,
            q_bragg=np.array(self.get_normalized_q_bragg_laboratory_frame[::-1]),
            initial_shape=self.original_shape,
            voxel_size=self.parameters["fix_voxel"],
            reference_axis=AXIS_TO_ARRAY[self.parameters["ref_axis_q"]],
            fill_value=0,
            debugging=True,
            title="modulus",
            cmap=self.parameters["colormap"].cmap,
        )
        self.data = obj_ortho
        self.voxel_sizes = voxel_sizes
        self.update_parameters(
            {"transformation_matrix": transfer_matrix, "is_orthogonal": True}
        )


class OrthogonalFrame(Analysis):
    """Analysis workflow for data already in an orthogonal frame."""

    @property
    def is_data_in_laboratory_frame(self):
        return self.parameters["data_frame"] == "laboratory"

    @property
    def user_defined_voxel_size(self):
        return self.parameters["fix_voxel"]

    def calculate_voxel_sizes(self) -> List[float]:
        """Calculate the direct space voxel sizes based on loaded q values."""
        file = self.load_q_values()
        qx = file["qx"]
        qy = file["qy"]
        qz = file["qz"]
        dy_real = (
            2 * np.pi / abs(qz.max() - qz.min()) / 10
        )  # in nm qz=y in nexus convention
        dx_real = (
            2 * np.pi / abs(qy.max() - qy.min()) / 10
        )  # in nm qy=x in nexus convention
        dz_real = (
            2 * np.pi / abs(qx.max() - qx.min()) / 10
        )  # in nm qx=z in nexus convention
        self.logger.info(
            f"direct space voxel size from q values: ({dz_real:.2f} nm,"
            f" {dy_real:.2f} nm, {dx_real:.2f} nm)"
        )
        return [dz_real, dy_real, dx_real]

    def interpolate_into_crystal_frame(self) -> None:
        """Regrid and rotate the data if necessary."""
        self.update_parameters({"is_orthogonal": True})
        self.voxel_sizes = self.calculate_voxel_sizes()
        if self.user_defined_voxel_size:
            self.regrid(self.user_defined_voxel_size)
        if self.is_data_in_laboratory_frame:
            self.rotate_into_crystal_frame()

    def rotate_into_crystal_frame(self) -> None:
        self.logger.info(
            "Rotating the object in the crystal frame " "for the strain calculation"
        )
        amp, phase = util.rotate_crystal(
            arrays=(abs(self.data), np.angle(self.data)),
            is_orthogonal=True,
            reciprocal_space=False,
            voxel_size=self.voxel_sizes,
            debugging=(True, False),
            axis_to_align=self.get_normalized_q_bragg_laboratory_frame[::-1],
            reference_axis=AXIS_TO_ARRAY[self.parameters["ref_axis_q"]],
            title=("amp", "phase"),
            cmap=self.parameters["colormap"].cmap,
        )
        self.data = amp * np.exp(1j * phase)

    def load_q_values(self) -> Any:
        try:
            self.logger.info("Select the file containing QxQzQy")
            file_path = filedialog.askopenfilename(
                title="Select the file containing QxQzQy",
                initialdir=self.setup.detector.savedir,
                filetypes=[("NPZ", "*.npz")],
            )
            return np.load(file_path)
        except FileNotFoundError:
            raise FileNotFoundError(
                "q values not provided, the voxel size cannot be calculated"
            )

    def regrid(self, new_voxelsizes: List[float]) -> None:
        """Regrid the data based on user-defined voxel sizes."""
        valid.valid_container(
            new_voxelsizes,
            container_types=(list, tuple),
            item_types=(float, int),
            min_excluded=0,
            allow_none=False,
            name="new_voxelsizes",
        )
        self.logger.info(
            f"Direct space pixel size for the interpolation: {new_voxelsizes} (nm)"
        )
        self.logger.info("Interpolating...\n")
        self.data = pu.regrid(
            array=self.data,
            old_voxelsize=self.voxel_sizes,
            new_voxelsize=new_voxelsizes,
        )
        self.voxel_sizes = self.parameters["fix_voxel"]


class PhaseManipulator:
    """Process the phase of the data."""

    def __init__(
        self,
        data: np.ndarray,
        parameters: Dict[str, Any],
        original_shape: Tuple[int, ...],
        save_directory: Optional[str] = None,
        **kwargs,
    ) -> None:
        self.data = data
        self._phase, self._modulus = self.extract_phase_modulus()
        self.parameters = parameters
        self.original_shape = original_shape
        self.save_directory = save_directory

        self._extent_phase: Optional[float] = None
        self._phase_ramp: Optional[List[float]] = None
        self.logger = kwargs.get("logger", module_logger)

    @property
    def extent_phase(self) -> Optional[float]:
        return self._extent_phase

    @property
    def modulus(self) -> np.ndarray:
        return self._modulus

    @property
    def phase(self) -> np.ndarray:
        return self._phase

    @property
    def phase_ramp(self) -> Optional[List[float]]:
        return self._phase_ramp

    @property
    def save_directory(self) -> Optional[str]:
        return self._save_directory

    @save_directory.setter
    def save_directory(self, val: Optional[str]) -> None:
        if isinstance(val, str) and not val.endswith("/"):
            val += "/"
        self._save_directory = val

    def add_ramp(self, sign: int = +1) -> None:
        """Add a linear ramp to the phase."""
        if self.phase_ramp is None:
            raise ValueError("'phase_ramp' is None, can't add the phase ramp")
        gridz, gridy, gridx = np.meshgrid(
            np.arange(0, self.data.shape[0], 1),
            np.arange(0, self.data.shape[1], 1),
            np.arange(0, self.data.shape[2], 1),
            indexing="ij",
        )

        self._phase = (
            self.phase
            + gridz * sign * self.phase_ramp[0]
            + gridy * sign * self.phase_ramp[1]
            + gridx * sign * self.phase_ramp[2]
        )

    def apodize(self) -> None:
        """Apply a filtering window to the phase."""
        self._modulus, self._phase = pu.apodize(
            amp=self.modulus,
            phase=self.phase,
            initial_shape=self.original_shape,
            window_type=self.parameters["apodization_window"],
            sigma=self.parameters["apodization_sigma"],
            mu=self.parameters["apodization_mu"],
            alpha=self.parameters["apodization_alpha"],
            is_orthogonal=self.parameters["is_orthogonal"],
            debugging=True,
            cmap=self.parameters["colormap"].cmap,
        )

    def average_phase(self) -> None:
        """Apply an averaging window to the phase."""
        bulk = pu.find_bulk(
            amp=self.modulus,
            support_threshold=self.parameters["isosurface_strain"],
            method="threshold",
            cmap=self.parameters["colormap"].cmap,
        )
        # the phase should be averaged only in the support defined by the isosurface
        self._phase = pu.mean_filter(
            array=self.phase,
            support=bulk,
            half_width=self.parameters["half_width_avg_phase"],
            cmap=self.parameters["colormap"].cmap,
        )

    def center_phase(self) -> None:
        """Wrap the phase around its mean."""
        if self.extent_phase is None:
            raise ValueError("'extent_phase' is None, can't center the phase")
        self._phase = util.wrap(
            self.phase,
            start_angle=-self.extent_phase / 2,
            range_angle=self.extent_phase,
        )

    def extract_phase_modulus(self) -> Tuple[np.ndarray, np.ndarray]:
        """Get the phase and the modulus out of the data."""
        return np.angle(self.data), abs(self.data)

    def invert_phase(self) -> None:
        self._phase = -1 * self.phase

    def plot_phase(self, plot_title: str = "", save_plot: bool = False) -> None:
        fig, _, _ = gu.multislices_plot(
            self.phase,
            plot_colorbar=True,
            title=plot_title,
            reciprocal_space=False,
            is_orthogonal=self.parameters["is_orthogonal"],
            cmap=self.parameters["colormap"].cmap,
        )
        if save_plot and self.save_directory is not None:
            fig.savefig(self.save_directory + plot_title + ".png")

    def remove_offset(self) -> None:
        """Remove a phase offset to the phase."""
        support = np.zeros(self.data.shape)
        support[
            self.modulus > self.parameters["isosurface_strain"] * self.modulus.max()
        ] = 1
        self._phase = pu.remove_offset(
            array=self.phase,
            support=support,
            offset_method=self.parameters["offset_method"],
            phase_offset=self.parameters["phase_offset"],
            offset_origin=self.parameters["phase_offset_origin"],
            title="Phase",
            debugging=self.parameters["debug"],
            cmap=self.parameters["colormap"].cmap,
        )

    def remove_ramp(self) -> None:
        """Remove the linear trend in the phase based on a modulus support."""
        self._modulus, self._phase, *self._phase_ramp = pu.remove_ramp(
            amp=self.modulus,
            phase=self.phase,
            initial_shape=self.original_shape,
            method="gradient",
            amplitude_threshold=self.parameters["isosurface_strain"],
            threshold_gradient=self.parameters["threshold_gradient"],
            cmap=self.parameters["colormap"].cmap,
            logger=self.logger,
        )

    def unwrap_phase(self) -> None:
        self._phase, self._extent_phase = pu.unwrap(
            self.data,
            support_threshold=self.parameters["threshold_unwrap_refraction"],
            debugging=self.parameters["debug"],
            reciprocal_space=False,
            is_orthogonal=self.parameters["is_orthogonal"],
            cmap=self.parameters["colormap"].cmap,
        )

        self.logger.info(
            "Extent of the phase over an extended support (ceil(phase range)) ~ "
            f"{int(self.extent_phase)} (rad)",
        )


def define_analysis_type(data_frame: str, interpolation_method: str) -> str:
    """Define the correct analysis type depending on the parameters."""
    if data_frame == "detector":
        return interpolation_method
    return "orthogonal"


def create_analysis(
    scan_index: int,
    parameters: Dict[str, Any],
    setup: Setup,
    **kwargs,
) -> Analysis:
    """Create the correct analysis class depending on the parameters."""
    name = define_analysis_type(
        data_frame=parameters["data_frame"],
        interpolation_method=parameters["interpolation_method"],
    )
    if name == "linearization":
        return DetectorFrameLinearization(
            scan_index=scan_index,
            parameters=parameters,
            setup=setup,
            **kwargs,
        )
    if name == "orthogonal":
        return OrthogonalFrame(
            scan_index=scan_index,
            parameters=parameters,
            setup=setup,
            **kwargs,
        )
    raise ValueError(f"Analysis {name} not supported")
