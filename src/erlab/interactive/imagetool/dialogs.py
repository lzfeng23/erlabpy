"""Dialogs for data manipulation found in the menu bar."""

from __future__ import annotations

import typing
import weakref

import numpy as np
import numpy.typing as npt
import xarray as xr
from qtpy import QtCore, QtGui, QtWidgets

import erlab

if typing.TYPE_CHECKING:
    from collections.abc import Hashable

    from erlab.interactive.imagetool.core import ColorMapState, ImageSlicerArea
    from erlab.interactive.imagetool.slicer import ArraySlicer


class _DataManipulationDialog(QtWidgets.QDialog):
    """Parent class for a dialog that manipulates data.

    In practice, use child classes `DataTransformDialog` and `DataFilterDialog`.
    """

    whatsthis: str | None = None
    """The whatsthis text for the dialog window."""

    title: str | None = None
    """The title of the dialog window."""

    enable_copy: bool = False
    """Whether to show a button to copy the code to the clipboard.

    If True, the button will be shown in the dialog box. The `make_code` method must be
    overridden to provide the code to be copied.
    """

    _sigCodeCopied = QtCore.Signal(str)

    def __init__(self, slicer_area: ImageSlicerArea) -> None:
        super().__init__()
        if self.title is not None:
            self.setWindowTitle(self.title)

        self.slicer_area = slicer_area

        self._layout = QtWidgets.QFormLayout()
        self.setLayout(self._layout)

        if self.whatsthis is not None:
            self.setWhatsThis(self.whatsthis)
            self.setWindowFlags(
                self.windowFlags() | QtCore.Qt.WindowType.WindowContextHelpButtonHint
            )

        self.buttonBox = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.StandardButton.Ok
            | QtWidgets.QDialogButtonBox.StandardButton.Cancel
        )
        if self.enable_copy:
            self.copy_button = QtWidgets.QPushButton("Copy Code")
            self.copy_button.clicked.connect(self._copy)
            self.buttonBox.addButton(
                self.copy_button, QtWidgets.QDialogButtonBox.ButtonRole.ActionRole
            )

        self.setup_widgets()

        self.buttonBox.accepted.connect(self.accept)
        self.buttonBox.rejected.connect(self.reject)
        self.layout_.addRow(self.buttonBox)

    @property
    def layout_(self) -> QtWidgets.QFormLayout:
        return self._layout

    @property
    def slicer_area(self) -> ImageSlicerArea:
        _slicer_area = self._slicer_area()
        if _slicer_area:
            return _slicer_area
        raise LookupError("Parent was destroyed")

    @slicer_area.setter
    def slicer_area(self, value: ImageSlicerArea) -> None:
        self._slicer_area = weakref.ref(value)

    @property
    def array_slicer(self) -> ArraySlicer:
        return self.slicer_area.array_slicer

    @QtCore.Slot()
    def _copy(self) -> None:
        code = self.make_code()
        if code:
            self._sigCodeCopied.emit(erlab.interactive.utils.copy_to_clipboard(code))
        else:
            QtWidgets.QMessageBox.warning(
                self, "Nothing to Copy", "Generated code is empty."
            )

    def setup_widgets(self) -> None:
        # Overridden by subclasses
        pass

    def process_data(self, data: xr.DataArray) -> xr.DataArray:
        # Overridden by subclasses
        return data

    def make_code(self) -> str:
        # Overridden by subclasses
        return ""


class DataTransformDialog(_DataManipulationDialog):
    """Parent class for implementing data changes that affect both shape and values.

    These changes are destructive and cannot be undone. The user can choose to open the
    transformed data in a new window or replace the current data.

    - Override method `setup_widgets` to add widgets to the dialog.

    - Override method `process_data` to implement the data transformation.

    - Override method `make_code` to generate code that can be copied to the clipboard.

    - Override attribute `title` to set the title of the dialog window.

    - Override attribute `enable_copy` to show or hide the copy button.

    - Override attributes `prefix` and `suffix` to set the prefix and suffix of the new
      data name.

    - Override attribute `keep_colors` and `keep_color_limits` to control which
      color-related settings are migrated when opening in a new window.

    """

    prefix: str = ""
    suffix: str = ""

    keep_colors: bool = True
    """Whether to keep the color settings when opening in a new window.

    If True, the same colormap and normalization is used in the new window.
    """

    keep_color_limits: bool = True
    """Whether to also keep manual color limits when opening in a new window."""

    def __init__(self, slicer_area: ImageSlicerArea) -> None:
        super().__init__(slicer_area)
        self.new_window_check = QtWidgets.QCheckBox("Open in New Window")
        self.new_window_check.setChecked(True)
        self.layout_.insertRow(-1, self.new_window_check)

    @QtCore.Slot()
    def accept(self) -> None:
        if self.slicer_area.data.name is not None:
            new_name = f"{self.prefix}{self.slicer_area.data.name}{self.suffix}"
        else:
            new_name = None

        try:
            applied_func = None
            if self.slicer_area._applied_func is not None:
                # Transform must be done on unfiltered data
                applied_func = self.slicer_area._applied_func
                self.slicer_area.apply_func(None)

            processed = erlab.interactive.imagetool.slicer.restore_nonuniform_dims(
                self.process_data(self.slicer_area.data)
            ).rename(new_name)

            if self.new_window_check.isChecked():
                itool_kw: dict[str, typing.Any] = {
                    "data": processed,
                    "execute": False,
                }

                if self.keep_colors:
                    color_props: ColorMapState = self.slicer_area.colormap_properties

                    itool_kw["cmap"] = color_props["cmap"]
                    itool_kw["gamma"] = color_props["gamma"]
                    itool_kw["high_contrast"] = color_props["high_contrast"]
                    itool_kw["zero_centered"] = color_props["zero_centered"]

                    if color_props["levels_locked"] and self.keep_color_limits:
                        itool_kw["vmin"], itool_kw["vmax"] = color_props["levels"]

                erlab.interactive.itool(**itool_kw)
            else:
                self.slicer_area.set_data(processed)

            del processed

            if applied_func is not None:
                self.slicer_area.apply_func(applied_func)

        except Exception as e:
            QtWidgets.QMessageBox.critical(self, "Error", f"An error occurred: {e}")
            return

        super().accept()


class DataFilterDialog(_DataManipulationDialog):
    """Parent class for implementing data changes that only affects the appearance.

    These changes are not destructive and can be undone from the menu bar. Only one kind
    of filter can be applied at a time, and applying a new kind of filter will replace
    the previous one.

    - Override method `setup_widgets` to add widgets to the dialog.

    - Override method `process_data` to implement the filter. The output must be a new
      DataArray with the same shape as the input.

    - Override method `make_code` to generate code that can be copied to the clipboard.

    - Override attribute `title` to set the title of the dialog window.

    - Override attribute `enable_copy` to show or hide the copy button.

    - Override attributes `enable_preview` to show or hide the preview button.

    """

    enable_preview: bool = True
    """Whether to show a preview button."""

    def __init__(self, slicer_area: ImageSlicerArea) -> None:
        super().__init__(slicer_area)
        self._previewed: bool = False

        if self.enable_preview:
            self.preview_button = QtWidgets.QPushButton("Preview")
            self.preview_button.clicked.connect(self._preview)
            self.buttonBox.addButton(
                self.preview_button, QtWidgets.QDialogButtonBox.ButtonRole.ActionRole
            )

    @QtCore.Slot()
    def _preview(self):
        self._previewed = True
        self.slicer_area.apply_func(self.process_data)

    @QtCore.Slot()
    def reject(self) -> None:
        if self._previewed:
            self.slicer_area.apply_func(None)
        super().reject()

    @QtCore.Slot()
    def accept(self) -> None:
        try:
            self.slicer_area.apply_func(self.process_data)
        except Exception as e:
            QtWidgets.QMessageBox.critical(self, "Error", f"An error occurred: {e}")
            return
        super().accept()


class RotationDialog(DataTransformDialog):
    enable_copy = True

    @property
    def suffix(self) -> str:
        angle_str = str(self._rotate_params["angle"])
        return f"_rot{angle_str}"

    @suffix.setter
    def suffix(self, value: str) -> None:
        # To satisfy mypy
        pass

    @property
    def _rotate_params(self) -> dict[str, typing.Any]:
        return {
            "angle": float(
                np.round(self.angle_spin.value(), self.angle_spin.decimals())
            ),
            "axes": typing.cast(
                "tuple[str, str]", tuple(self.slicer_area.main_image.axis_dims_uniform)
            ),
            "center": typing.cast(
                "tuple[float, float]", tuple(spin.value() for spin in self.center_spins)
            ),
            "reshape": self.reshape_check.isChecked(),
            "order": self.order_spin.value(),
        }

    def setup_widgets(self) -> None:
        main_image = self.slicer_area.main_image
        self.angle_spin = QtWidgets.QDoubleSpinBox()
        self.angle_spin.setRange(-360, 360)
        self.angle_spin.setSingleStep(1)
        self.angle_spin.setValue(0)
        self.angle_spin.setDecimals(2)
        self.angle_spin.setSuffix("°")
        self.layout_.addRow("Angle", self.angle_spin)

        self.center_spins = (QtWidgets.QDoubleSpinBox(), QtWidgets.QDoubleSpinBox())
        for i in range(2):
            axis: int = main_image.display_axis[i]
            dim: str = str(main_image.axis_dims_uniform[i])

            self.center_spins[i].setRange(
                *map(float, self.array_slicer.lims_uniform[i])
            )
            self.center_spins[i].setSingleStep(float(self.array_slicer.incs_uniform[i]))
            self.center_spins[i].setValue(0.0)
            self.center_spins[i].setDecimals(
                self.array_slicer.get_significant(axis, uniform=True)
            )

            self.layout_.addRow(f"Center {dim}", self.center_spins[i])

        self.order_spin: QtWidgets.QSpinBox = QtWidgets.QSpinBox()
        self.order_spin.setRange(0, 5)
        self.order_spin.setValue(1)
        self.layout_.addRow("Spline Order", self.order_spin)

        self.reshape_check: QtWidgets.QCheckBox = QtWidgets.QCheckBox("Reshape")
        self.reshape_check.setChecked(True)
        self.layout_.addRow(self.reshape_check)

        if main_image.is_guidelines_visible:
            # Fill values from guideline
            self.angle_spin.setValue(-main_image._guideline_angle)
            for spin, val in zip(
                self.center_spins, main_image._guideline_offset, strict=True
            ):
                spin.setValue(val)

    def process_data(self, data: xr.DataArray) -> xr.DataArray:
        return erlab.analysis.transform.rotate(data, **self._rotate_params)

    def make_code(self) -> str:
        placeholder = " "
        return erlab.interactive.utils.generate_code(
            erlab.analysis.transform.rotate,
            [f"|{placeholder}|"],
            self._rotate_params,
            module="era.transform",
        )


class AverageDialog(DataTransformDialog):
    title = "Average Over Dimensions"
    suffix = "_avg"
    enable_copy = True

    def setup_widgets(self) -> None:
        dim_group = QtWidgets.QGroupBox("Dimensions")
        dim_layout = QtWidgets.QVBoxLayout()
        dim_group.setLayout(dim_layout)

        self.dim_checks: dict[Hashable, QtWidgets.QCheckBox] = {}

        for d in self.slicer_area.data.dims:
            self.dim_checks[d] = QtWidgets.QCheckBox(str(d))
            dim_layout.addWidget(self.dim_checks[d])

        self.layout_.addRow(dim_group)

    @property
    def _target_dims(self) -> tuple[Hashable, ...]:
        return tuple(k for k, v in self.dim_checks.items() if v.isChecked())

    def process_data(self, data: xr.DataArray) -> xr.DataArray:
        return data.qsel.average(self._target_dims)

    @QtCore.Slot()
    def accept(self) -> None:
        if self._target_dims == {}:
            QtWidgets.QMessageBox.warning(
                self,
                "No Dimensions Selected",
                "You need to select at least one dimension.",
            )
            return

        if (self.slicer_area.data.ndim - len(self._target_dims)) < 2:
            QtWidgets.QMessageBox.warning(
                self,
                "Not Enough Dimensions Left",
                "Data must have at least 2 dimensions after averaging to be displayed.",
            )
            return

        super().accept()

    def make_code(self) -> str:
        arg = (
            str(self._target_dims)
            if len(self._target_dims) > 1
            else f'"{self._target_dims[0]}"'
        )
        return f".qsel.average({arg})"


class SymmetrizeDialog(DataTransformDialog):
    title = "Symmetrize"
    enable_copy = True

    @property
    def suffix(self) -> str:
        return f"_sym_{self._params['dim']}"

    @suffix.setter
    def suffix(self, value: str) -> None:
        # To satisfy mypy
        pass

    def setup_widgets(self) -> None:
        dim_group = QtWidgets.QGroupBox("Mirror plane")
        dim_layout = QtWidgets.QHBoxLayout()
        dim_group.setLayout(dim_layout)

        self._dim_combo = QtWidgets.QComboBox()
        self._dim_combo.addItems([str(d) for d in self.slicer_area.data.dims])
        dim_layout.addWidget(self._dim_combo)

        self._center_spin = QtWidgets.QDoubleSpinBox()
        dim_layout.addWidget(self._center_spin)
        self._dim_combo.currentIndexChanged.connect(self._update_spin)
        self._update_spin()

        option_group = QtWidgets.QGroupBox("Options")
        option_group_layout = QtWidgets.QVBoxLayout()
        option_group.setLayout(option_group_layout)

        self.subtract_check = QtWidgets.QCheckBox("Subtract")
        self.subtract_check.setChecked(False)
        self.subtract_check.setToolTip(
            "Subtract the reflected part from the data instead of adding it."
        )
        option_group_layout.addWidget(self.subtract_check)

        option_mode = QtWidgets.QWidget()
        option_group_layout.addWidget(option_mode)
        option_mode_layout = QtWidgets.QHBoxLayout()
        option_mode_layout.setContentsMargins(0, 0, 0, 0)
        option_mode.setLayout(option_mode_layout)
        option_mode_layout.addWidget(QtWidgets.QLabel("Mode:"))
        self.opt_mode: list[QtWidgets.QRadioButton] = []
        self.opt_mode.append(QtWidgets.QRadioButton("full"))
        self.opt_mode.append(QtWidgets.QRadioButton("valid"))
        self.opt_mode[0].setChecked(True)
        for opt in self.opt_mode:
            option_mode_layout.addWidget(opt)

        option_part = QtWidgets.QWidget()
        option_group_layout.addWidget(option_part)
        option_part_layout = QtWidgets.QHBoxLayout()
        option_part_layout.setContentsMargins(0, 0, 0, 0)
        option_part.setLayout(option_part_layout)
        option_part_layout.addWidget(QtWidgets.QLabel("Part to Keep:"))
        self.opt_part: list[QtWidgets.QRadioButton] = []
        self.opt_part.append(QtWidgets.QRadioButton("both"))
        self.opt_part.append(QtWidgets.QRadioButton("below"))
        self.opt_part.append(QtWidgets.QRadioButton("above"))
        self.opt_part[0].setChecked(True)
        for opt in self.opt_part:
            option_part_layout.addWidget(opt)

        self.layout_.addRow(dim_group)
        self.layout_.addRow(option_group)

    @QtCore.Slot()
    def _update_spin(self) -> None:
        axis = self._dim_combo.currentIndex()
        self._center_spin.setRange(*map(float, self.array_slicer.lims_uniform[axis]))
        self._center_spin.setSingleStep(float(self.array_slicer.incs_uniform[axis]))
        self._center_spin.setDecimals(
            self.array_slicer.get_significant(axis, uniform=True)
        )
        self._center_spin.setValue(
            self.slicer_area.current_values_uniform[self._dim_combo.currentIndex()]
        )

    @property
    def _params(self) -> dict[str, typing.Any]:
        return {
            "dim": self._dim_combo.currentText(),
            "center": float(
                np.round(self._center_spin.value(), self._center_spin.decimals())
            ),
            "subtract": self.subtract_check.isChecked(),
            "mode": ("full", "valid")[
                next(i for i, opt in enumerate(self.opt_mode) if opt.isChecked())
            ],
            "part": ("both", "below", "above")[
                next(i for i, opt in enumerate(self.opt_part) if opt.isChecked())
            ],
        }

    def process_data(self, data: xr.DataArray) -> xr.DataArray:
        return erlab.analysis.transform.symmetrize(data, **self._params)

    def make_code(self) -> str:
        placeholder = " "
        return erlab.interactive.utils.generate_code(
            erlab.analysis.transform.symmetrize,
            [f"|{placeholder}|"],
            self._params,
            module="era.transform",
        )


class EdgeCorrectionDialog(DataTransformDialog):
    title = "Edge Correction"
    suffix = "_corr"
    enable_copy = False

    def setup_widgets(self) -> None:
        self.shift_coord_check = QtWidgets.QCheckBox("Shift Coordinates")
        self.shift_coord_check.setChecked(True)

        self.layout_.addRow(self.shift_coord_check)

    def process_data(self, data: xr.DataArray) -> xr.DataArray:
        return erlab.analysis.gold.correct_with_edge(
            data,
            self._edge_fit,
            shift_coords=self.shift_coord_check.isChecked(),
        )

    def exec(self) -> int:
        if "eV" not in self.slicer_area.data.dims:
            QtWidgets.QMessageBox.warning(
                self,
                "No Energy Dimension",
                "Edge correction requires an energy dimension (eV) in the data.",
            )
            return QtWidgets.QDialog.DialogCode.Rejected

        self._edge_fit: xr.Dataset | None = erlab.interactive.utils.load_fit_ui()
        if self._edge_fit is None:
            # User canceled the fit dialog
            return QtWidgets.QDialog.DialogCode.Rejected
        return super().exec()


class _BaseCropDialog(DataTransformDialog):
    suffix = "_crop"
    enable_copy = True

    @property
    def _slice_kwargs(self) -> dict[Hashable, slice]:
        raise NotImplementedError

    def process_data(self, data: xr.DataArray) -> xr.DataArray:
        return data.sel(self._slice_kwargs)

    def make_code(self) -> str:
        kwargs: dict[Hashable, slice] = dict(self._slice_kwargs)

        isel_kwargs: dict[str, slice] = {}
        for k in list(kwargs.keys()):
            if str(k).endswith("_idx"):
                isel_kwargs[str(k).removesuffix("_idx")] = kwargs.pop(k)

        out: str = ""

        if kwargs:
            if all(isinstance(k, str) and str(k).isidentifier() for k in kwargs):
                out = erlab.interactive.utils.generate_code(
                    xr.DataArray.sel,
                    [],
                    kwargs=typing.cast("dict[str, slice]", kwargs),
                    module=out,
                )
            else:
                out += f".sel({kwargs})"

        if isel_kwargs:
            if all(k.isidentifier() for k in isel_kwargs):
                out = erlab.interactive.utils.generate_code(
                    xr.DataArray.isel, [], isel_kwargs, module=out
                )
            else:
                out += f".isel({isel_kwargs})"

        return out.replace(", None)", ")")


class CropToViewDialog(_BaseCropDialog):
    title = "Crop to View"
    whatsthis = "Crop the data to the currently visible area."

    def setup_widgets(self) -> None:
        dim_group = QtWidgets.QGroupBox("Dimensions")
        dim_layout = QtWidgets.QVBoxLayout()
        dim_group.setLayout(dim_layout)

        self.dim_checks: dict[Hashable, QtWidgets.QCheckBox] = {}

        for i, d in enumerate(self.slicer_area.data.dims):
            self.dim_checks[d] = QtWidgets.QCheckBox(str(d))
            dim_layout.addWidget(self.dim_checks[d])
            if i < 2:
                # Enable first 2 dimensions by default
                self.dim_checks[d].setChecked(True)

            if d not in self.slicer_area.manual_limits:
                # Disable dimensions without manual limits
                self.dim_checks[d].setChecked(False)
                self.dim_checks[d].setDisabled(True)

        self.layout_.addRow(dim_group)

    @property
    def _slice_kwargs(self) -> dict[Hashable, slice]:
        slice_dict: dict[Hashable, slice] = {}
        for k, v in self.slicer_area.manual_limits.items():
            if self.dim_checks[k].isChecked():
                ax_idx = self.slicer_area.data.dims.index(k)
                sig_digits = self.array_slicer.get_significant(ax_idx, uniform=True)
                slice_dict[k] = slice(
                    *sorted(float(np.round(val, sig_digits)) for val in v)
                )

        return slice_dict

    @QtCore.Slot()
    def accept(self) -> None:
        if self._slice_kwargs == {}:
            QtWidgets.QMessageBox.warning(
                self,
                "No Dimensions Selected",
                "You need to select at least one dimension with manual limits.",
            )
            return
        super().accept()

    def exec(self) -> int:
        if len(self.slicer_area.manual_limits) == 0:
            QtWidgets.QMessageBox.warning(
                self, "Nothing to Crop", "Manually zoom in to define the crop area."
            )
            return QtWidgets.QDialog.DialogCode.Rejected
        return super().exec()


class CropDialog(_BaseCropDialog):
    title = "Crop Between Cursors"

    @property
    def _enabled_dims(self) -> list[Hashable]:
        return [k for k, v in self.dim_checks.items() if v.isChecked()]

    @property
    def _cursor_indices(self) -> tuple[int, int]:
        return typing.cast(
            "tuple[int, int]",
            tuple(combo.currentIndex() for combo in self.cursor_combos),
        )

    @property
    def _slice_kwargs(self) -> dict[Hashable, slice]:
        c0, c1 = self._cursor_indices

        slice_dict: dict[Hashable, slice] = {}

        for k in self._enabled_dims:
            ax_idx = self.slicer_area.data.dims.index(k)
            sig_digits = self.array_slicer.get_significant(ax_idx, uniform=True)

            v0 = self.array_slicer.get_value(cursor=c0, axis=ax_idx, uniform=True)
            v1 = self.array_slicer.get_value(cursor=c1, axis=ax_idx, uniform=True)

            if v0 > v1:
                v0, v1 = v1, v0

            slice_dict[k] = slice(
                float(np.round(v0, sig_digits)), float(np.round(v1, sig_digits))
            )

        return slice_dict

    def exec(self) -> int:
        if self.slicer_area.n_cursors == 1:
            QtWidgets.QMessageBox.warning(
                self, "Only 1 Cursor", "You need at least 2 cursors to crop the data."
            )
            return QtWidgets.QDialog.DialogCode.Rejected
        return super().exec()

    @QtCore.Slot()
    def accept(self) -> None:
        if self._slice_kwargs == {}:
            QtWidgets.QMessageBox.warning(
                self,
                "No Dimensions Selected",
                "You need to select at least one dimension.",
            )
            return
        super().accept()

    def setup_widgets(self) -> None:
        if self.slicer_area.n_cursors == 1:
            return

        self._cursors_group = erlab.interactive.utils.ExclusiveComboGroup(self)

        self.cursor_combos: list[QtWidgets.QComboBox] = []

        cursor_group = QtWidgets.QGroupBox("Between")
        cursor_layout = QtWidgets.QHBoxLayout()
        cursor_group.setLayout(cursor_layout)

        for i in range(2):
            combo = QtWidgets.QComboBox()
            for cursor_idx in range(self.slicer_area.n_cursors):
                combo.addItem(
                    self.slicer_area._cursor_icon(cursor_idx),
                    self.slicer_area._cursor_name(cursor_idx),
                )
            combo.setCurrentIndex(i)
            combo.setMaximumHeight(QtGui.QFontMetrics(combo.font()).height() + 3)
            combo.setIconSize(QtCore.QSize(10, 10))
            cursor_layout.addWidget(combo)
            self._cursors_group.addCombo(combo)
            self.cursor_combos.append(combo)

        self.layout_.addRow(cursor_group)

        dim_group = QtWidgets.QGroupBox("Dimensions")
        dim_layout = QtWidgets.QVBoxLayout()
        dim_group.setLayout(dim_layout)

        self.dim_checks: dict[Hashable, QtWidgets.QCheckBox] = {}

        for d in self.slicer_area.data.dims:
            self.dim_checks[d] = QtWidgets.QCheckBox(str(d))
            dim_layout.addWidget(self.dim_checks[d])

        self.layout_.addRow(dim_group)


class NormalizeDialog(DataFilterDialog):
    title = "Normalize"
    enable_copy = False

    def setup_widgets(self) -> None:
        dim_group = QtWidgets.QGroupBox("Dimensions")
        dim_layout = QtWidgets.QVBoxLayout()
        dim_group.setLayout(dim_layout)

        self.dim_checks: dict[Hashable, QtWidgets.QCheckBox] = {}

        for d in self.slicer_area.data.dims:
            self.dim_checks[d] = QtWidgets.QCheckBox(str(d))
            dim_layout.addWidget(self.dim_checks[d])

        option_group = QtWidgets.QGroupBox("Options")
        option_layout = QtWidgets.QVBoxLayout()
        option_group.setLayout(option_layout)

        self.opts: list[QtWidgets.QRadioButton] = []
        self.opts.append(QtWidgets.QRadioButton("Data/Area"))
        self.opts.append(QtWidgets.QRadioButton("(Data−m)/(M−m)"))
        self.opts.append(QtWidgets.QRadioButton("Data−m"))
        self.opts.append(QtWidgets.QRadioButton("(Data−m)/Area"))

        self.opts[0].setChecked(True)
        for opt in self.opts:
            option_layout.addWidget(opt)

        self.layout_.addRow(dim_group)
        self.layout_.addRow(option_group)

    def process_data(self, data: xr.DataArray) -> xr.DataArray:
        norm_dims = tuple(k for k, v in self.dim_checks.items() if v.isChecked())
        if len(norm_dims) == 0:
            return data

        calc_area: bool = self.opts[0].isChecked() or self.opts[3].isChecked()
        calc_minimum: bool = not self.opts[0].isChecked()
        calc_maximum: bool = self.opts[1].isChecked()

        if calc_area:
            area = data.mean(norm_dims)

        if calc_minimum:
            minimum = data.min(norm_dims)

        if calc_maximum:
            maximum = data.max(norm_dims)

        if self.opts[0].isChecked():
            return data / area

        if self.opts[1].isChecked():
            return (data - minimum) / (maximum - minimum)

        if self.opts[2].isChecked():
            return data - minimum

        return (data - minimum) / area


class _CoordinateWidget(QtWidgets.QWidget):
    def __init__(self, values: npt.NDArray) -> None:
        super().__init__()
        self.init_ui()
        self.set_old_coord(values)

    def init_ui(self):
        container_layout = QtWidgets.QHBoxLayout(self)
        container_layout.setContentsMargins(0, 0, 0, 0)
        self.setLayout(container_layout)

        left_widget = QtWidgets.QWidget()
        container_layout.addWidget(left_widget)
        left_layout = QtWidgets.QFormLayout(left_widget)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_widget.setLayout(left_layout)

        self.spin0 = QtWidgets.QDoubleSpinBox()
        self.spin0.setRange(-1e9, 1e9)
        self.spin0.setSingleStep(0.01)
        self.spin0.setValue(0.0)
        self.spin0.setDecimals(4)
        self.spin0.setKeyboardTracking(False)
        left_layout.addRow("Start", self.spin0)
        self.spin0.valueChanged.connect(self.update_table)

        self.spin1 = QtWidgets.QDoubleSpinBox()
        self.spin1.setRange(-1e9, 1e9)
        self.spin1.setSingleStep(0.01)
        self.spin1.setValue(0.0)
        self.spin1.setDecimals(4)
        self.spin1.setKeyboardTracking(False)
        self.spin1.valueChanged.connect(self.update_table)

        self.mode_combo = QtWidgets.QComboBox()
        self.mode_combo.addItems(["End", "Delta"])
        self.mode_combo.setCurrentIndex(0)
        self.mode_combo.currentTextChanged.connect(self.mode_changed)
        left_layout.addRow(self.mode_combo, self.spin1)

        self.reset_btn = QtWidgets.QPushButton("Reset")
        left_layout.addRow(self.reset_btn)

        self.table = QtWidgets.QTableWidget()
        self.table.setColumnCount(1)
        self.table.horizontalHeader().setVisible(False)
        self.table.setSelectionBehavior(
            QtWidgets.QAbstractItemView.SelectionBehavior.SelectRows
        )
        self.table.setSortingEnabled(False)
        self.table.setAlternatingRowColors(True)
        left_layout.addRow(self.table)

    @QtCore.Slot()
    def mode_changed(self) -> None:
        """Handle the change of the mode combo box."""
        new_mode = self.mode_combo.currentText()
        self.spin1.blockSignals(True)
        match new_mode:
            case "End":
                self.spin1.setValue(self._current_values_delta[-1])
            case "Delta":
                arr = self._current_values_end
                self.spin1.setValue(arr[1] - arr[0])
        self.spin1.blockSignals(False)

    @QtCore.Slot()
    def reset(self) -> None:
        """Reset the spin boxes to the original values."""
        is_scalar: bool = np.atleast_1d(self._old_coord).size == 1
        self.spin0.setDisabled(is_scalar)
        self.spin1.setDisabled(is_scalar)
        self.mode_combo.setDisabled(is_scalar)

        if not is_scalar:
            self.spin0.blockSignals(True)
            self.spin1.blockSignals(True)
            if erlab.utils.array.is_uniform_spaced(self._old_coord):
                self.spin0.setValue(float(self._old_coord[0]))
                if self.mode_combo.currentText() == "End":
                    self.spin1.setValue(float(self._old_coord[-1]))
                else:
                    self.spin1.setValue(float(self._old_coord[1] - self._old_coord[0]))
            else:
                self.spin0.setValue(0.0)
                self.spin1.setValue(0.0)
            self.spin0.blockSignals(False)
            self.spin1.blockSignals(False)

        self._set_table_values(np.atleast_1d(self._old_coord))

    def set_old_coord(self, values: npt.NDArray) -> None:
        """Set the old coordinates to the given values."""
        self._old_coord = values.copy()
        self.reset()

    @property
    def _current_values_end(self) -> npt.NDArray:
        """Get the current values assuming spin1 value is the end."""
        return np.linspace(self.spin0.value(), self.spin1.value(), len(self._old_coord))

    @property
    def _current_values_delta(self) -> npt.NDArray:
        """Get the current values assuming spin1 value is the step size."""
        sz: int = len(self._old_coord)
        return np.linspace(
            self.spin0.value(),
            self.spin0.value() + self.spin1.value() * (sz - 1),
            sz,
        )

    @property
    def new_coord(self) -> npt.NDArray:
        """Get the edited coordinates as a numpy array."""
        values = self._old_coord.copy()
        for i in range(self.table.rowCount()):
            item = self.table.item(i, 0)
            if item is not None and item.text():
                try:
                    values[i] = float(item.text())
                except Exception as e:
                    raise ValueError(f"Invalid value in row {i}: {item.text()}") from e
        return values

    @QtCore.Slot()
    def update_table(self) -> None:
        """Update the table with the current values from the spin boxes."""
        match self.mode_combo.currentText():
            case "End":
                vals = self._current_values_end
            case _:
                vals = self._current_values_delta
        self._set_table_values(vals)

    def _set_table_values(self, values: npt.NDArray) -> None:
        """Set the table contents to the given numpy array."""
        self.table.setRowCount(len(values))
        # Make zero-based
        self.table.setVerticalHeaderLabels([str(i) for i in range(len(values))])
        for i, val in enumerate(values):
            item = QtWidgets.QTableWidgetItem(np.format_float_positional(val, trim="-"))
            item.setTextAlignment(
                QtCore.Qt.AlignmentFlag.AlignRight
                | QtCore.Qt.AlignmentFlag.AlignVCenter
            )
            self.table.setItem(i, 0, item)


class AssignCoordsDialog(DataTransformDialog):
    title = "Coordinate Editor"

    def setup_widgets(self) -> None:
        existing_widget = QtWidgets.QWidget(self)
        existing_layout = QtWidgets.QVBoxLayout(existing_widget)
        existing_layout.setContentsMargins(0, 0, 0, 0)
        self.layout_.addRow(existing_widget)

        existing_coord_names: list[str] = [str(d) for d in self.slicer_area.data.dims]
        existing_coord_names.extend(
            str(k)
            for k in self.slicer_area.data.coords
            if k not in self.slicer_area.data.dims
        )
        self._coord_combo = QtWidgets.QComboBox()
        self._coord_combo.addItems(existing_coord_names)
        existing_layout.addWidget(self._coord_combo)

        self._coord_combo.currentTextChanged.connect(self._coord_selection_changed)

        self.coord_widget = _CoordinateWidget(np.array([0, 1]))
        self._coord_selection_changed()
        existing_layout.addWidget(self.coord_widget)

    @property
    def current_coord_name(self) -> str:
        """Get the name of the currently selected coordinate."""
        return self._coord_combo.currentText()

    @QtCore.Slot()
    def _coord_selection_changed(self) -> None:
        self.coord_widget.set_old_coord(
            self.slicer_area.data[self.current_coord_name].values
        )

    def process_data(self, data: xr.DataArray) -> xr.DataArray:
        return erlab.utils.array.sort_coord_order(
            data.assign_coords(
                {
                    self.current_coord_name: data[self.current_coord_name].copy(
                        data=self.coord_widget.new_coord
                    )
                }
            ),
            keys=data.coords.keys(),
            dims_first=False,
        )
