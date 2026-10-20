"""PySide6 review window for one human reviewer. Shows one local video at a time, no model output.

The window only receives Session.view() data (position, duration, audio) and the media path; it never
shows item identifiers, file names, Charades hints, strata or A0/A1/A2 results. All semantic choices
are the reviewer's; the window only records them, measures playback coverage and enforces the guide.
"""
from __future__ import annotations

import time

from PySide6.QtCore import Qt, QTimer, QUrl
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
from PySide6.QtMultimediaWidgets import QVideoWidget
from PySide6.QtWidgets import (
    QAbstractItemView,
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QListWidget,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QRadioButton,
    QScrollArea,
    QSlider,
    QVBoxLayout,
    QWidget,
)

from evaluation.annotation.coverage import (
    TIMING_TOLERANCE_SECONDS,
    PlaybackTracker,
    covered_seconds,
    fully_played,
    unplayed_seconds,
)
from evaluation.annotation.record import (
    CATEGORIES,
    CATEGORY_STATES,
    ESCALATIONS,
    MEDIA_EXCLUSIONS,
    NUDITY_CONTEXTS,
    validate,
    video_label,
)
from evaluation.annotation.session import LockedError, Session

STATE_TEXT = {"absent": "absent", "present": "présent", "uncertain": "incertain"}
LABEL_TEXT = {"positive": "POSITIVE", "negative": "NÉGATIVE", "uncertain": "INCERTAINE", "excluded": "EXCLUE",
              None: "— (catégories incomplètes)"}


class ReviewWindow(QMainWindow):
    def __init__(self, session: Session, *, autoplay: bool = False):
        super().__init__()
        self.session, self.autoplay = session, autoplay
        self.item_id, self.record, self.state = None, None, None
        self.tracker, self.opened_at = PlaybackTracker(), None
        self.editing_locked = False
        self.setWindowTitle(f"Annotation NSFW à l'aveugle — relecteur {session.identity['reviewer_id']} (seul)")
        self.player = QMediaPlayer(self)
        self.audio = QAudioOutput(self)
        self.player.setAudioOutput(self.audio)
        self.video = QVideoWidget()
        self.player.setVideoOutput(self.video)
        self.video.setAspectRatioMode(Qt.AspectRatioMode.KeepAspectRatio)
        self.player.positionChanged.connect(self._position_changed)
        # Any pause, stop, end of media or source change ends the current played segment.
        self.player.playbackStateChanged.connect(lambda *_: self.tracker.interrupt())
        self.player.mediaStatusChanged.connect(lambda *_: self.tracker.interrupt())
        self.player.durationChanged.connect(lambda ms: self.slider.setRange(0, ms))
        self.autosave = QTimer(self, singleShot=True, interval=800, timeout=self.save_draft)
        self._build()
        self._shortcuts()
        start = session.progress()["next"] or session.order[0]
        self.open_item(start)

    # ------------------------------------------------------------------ layout

    def _build(self):
        self.header = QLabel()
        self.header.setTextFormat(Qt.TextFormat.PlainText)
        self.play_button = QPushButton("Lecture / pause (Espace)", clicked=self.toggle_play)
        back = QPushButton("−5 s", clicked=lambda: self.seek_relative(-5))
        forward = QPushButton("+5 s", clicked=lambda: self.seek_relative(5))
        self.speed = QComboBox()
        self.speed.addItems(["0.5×", "1×", "1.5×", "2×"])
        self.speed.setCurrentIndex(1)
        self.speed.currentTextChanged.connect(self.set_rate)
        self.slider = QSlider(Qt.Orientation.Horizontal)
        self.slider.sliderPressed.connect(lambda: self.tracker.interrupt())
        self.slider.sliderMoved.connect(self.seek_to)
        self.time_label, self.coverage_label = QLabel(), QLabel()
        controls = QHBoxLayout()
        for widget in (self.play_button, back, forward, self.speed, self.time_label, self.coverage_label):
            controls.addWidget(widget)
        left = QVBoxLayout()
        left.addWidget(self.header)
        left.addWidget(self.video, 1)
        left.addWidget(self.slider)
        left.addLayout(controls)

        form = QVBoxLayout()
        self.category_groups = {}
        for category in CATEGORIES:
            box, row, group = QGroupBox(category), QHBoxLayout(), QButtonGroup(self)
            group.setExclusive(True)
            for state in CATEGORY_STATES:
                button = QRadioButton(STATE_TEXT[state])
                button.setProperty("state", state)
                group.addButton(button)
                row.addWidget(button)
            group.buttonClicked.connect(self._changed)
            box.setLayout(row)
            form.addWidget(box)
            self.category_groups[category] = group
        self.nudity_context = QComboBox()
        self.nudity_context.addItems(["", *NUDITY_CONTEXTS])
        self.nudity_context.currentIndexChanged.connect(self._changed)
        context_form = QFormLayout()
        context_form.addRow("nudity_context", self.nudity_context)
        form.addLayout(context_form)

        events = QGroupBox("Intervalles (catégories présentes ou incertaines)")
        events_layout = QVBoxLayout()
        self.events_list = QListWidget()
        self.events_list.setMaximumHeight(90)
        self.events_list.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.event_category = QComboBox()
        self.event_category.addItems(CATEGORIES)
        self.event_start, self.event_end = QDoubleSpinBox(), QDoubleSpinBox()
        for spin in (self.event_start, self.event_end):
            spin.setDecimals(1)
            spin.setSingleStep(0.5)
            spin.setSuffix(" s")
        row = QHBoxLayout()
        for widget in (self.event_category, self.event_start,
                       QPushButton("Début = position", clicked=lambda: self.event_start.setValue(self.position())),
                       self.event_end,
                       QPushButton("Fin = position", clicked=lambda: self.event_end.setValue(self.position()))):
            row.addWidget(widget)
        buttons = QHBoxLayout()
        buttons.addWidget(QPushButton("Ajouter l'intervalle", clicked=self.add_event))
        buttons.addWidget(QPushButton("Supprimer la sélection", clicked=self.remove_event))
        events_layout.addWidget(self.events_list)
        events_layout.addLayout(row)
        events_layout.addLayout(buttons)
        events.setLayout(events_layout)
        form.addWidget(events)

        self.watched = QCheckBox("J'ai regardé la vidéo en entier")
        self.listened = QCheckBox("J'ai écouté l'audio")
        for box in (self.watched, self.listened):
            box.toggled.connect(self._changed)
        form.addWidget(self.watched)
        form.addWidget(self.listened)
        self.escalation = QComboBox()
        self.escalation.addItems(ESCALATIONS)
        self.escalation.currentIndexChanged.connect(self._escalation_changed)
        self.exclusion = QComboBox(editable=True)
        self.exclusion.addItems(["", *MEDIA_EXCLUSIONS, *ESCALATIONS[1:]])
        self.exclusion.currentTextChanged.connect(self._changed)
        stop = QPushButton("Arrêter immédiatement (doute âge / consentement)", clicked=self.emergency_stop)
        stop.setStyleSheet("color: #a00000; font-weight: bold;")
        escalation_form = QFormLayout()
        escalation_form.addRow("Escalade", self.escalation)
        escalation_form.addRow("Motif d'exclusion", self.exclusion)
        form.addLayout(escalation_form)
        form.addWidget(stop)
        self.notes = QPlainTextEdit()
        self.notes.setPlaceholderText("Notes (jamais de transcription de paroles)")
        self.notes.setMaximumHeight(80)
        self.notes.textChanged.connect(self._changed)
        form.addWidget(self.notes)
        form.addStretch(1)
        # Decision, problems and navigation stay visible below the scrolling form at any window height.
        self.label_view, self.problems_view = QLabel(), QLabel()
        self.problems_view.setWordWrap(True)
        self.problems_view.setStyleSheet("color: #a00000;")
        footer = QVBoxLayout()
        footer.addWidget(self.label_view)
        footer.addWidget(self.problems_view)
        navigation = QHBoxLayout()
        navigation.addWidget(QPushButton("◀ Précédente", clicked=lambda: self.step(-1)))
        navigation.addWidget(QPushButton("Enregistrer (Ctrl+S)", clicked=self.save_draft))
        self.lock_button = QPushButton("Verrouiller", clicked=self.lock)
        navigation.addWidget(self.lock_button)
        self.amend_button = QPushButton("Corriger…", clicked=self.start_amendment)
        navigation.addWidget(self.amend_button)
        navigation.addWidget(QPushButton("Suivante ▶", clicked=lambda: self.step(1)))
        footer.addLayout(navigation)

        panel = QWidget()
        panel.setLayout(form)
        scroll = QScrollArea()
        scroll.setWidget(panel)
        scroll.setWidgetResizable(True)
        scroll.setMinimumWidth(400)
        right = QVBoxLayout()
        right.addWidget(scroll, 1)
        right.addLayout(footer)
        root = QHBoxLayout()
        root.addLayout(left, 1)
        root.addLayout(right)
        central = QWidget()
        central.setLayout(root)
        self.setCentralWidget(central)
        self.form_panel = panel
        available = self.screen().availableGeometry()  # fits 1366x768 laptops as well as larger screens
        self.resize(min(1400, int(available.width() * 0.95)), min(860, int(available.height() * 0.92)))

    def _shortcuts(self):
        QShortcut(QKeySequence(Qt.Key.Key_Space), self, activated=self.toggle_play)
        QShortcut(QKeySequence(Qt.Key.Key_Left), self, activated=lambda: self.seek_relative(-5))
        QShortcut(QKeySequence(Qt.Key.Key_Right), self, activated=lambda: self.seek_relative(5))
        QShortcut(QKeySequence("Ctrl+S"), self, activated=self.save_draft)

    # ------------------------------------------------------------------ items

    def open_item(self, item_id: str):
        if self.item_id is not None:
            self.save_draft()
        self.player.stop()
        self.player.setSource(QUrl())
        self.item_id, self.editing_locked = item_id, False
        self.record, self.state = self.session.load(item_id)
        self.tracker = PlaybackTracker(self.record.get("played_intervals", []))
        self.opened_at = time.monotonic()
        view = self.session.view(item_id)
        self.view = view
        for spin in (self.event_start, self.event_end):
            spin.setRange(0.0, view["duration_seconds"])
        media_ok = self.session.verify_media(item_id)
        if media_ok and self.record["escalation"] == "none":
            self.player.setSource(QUrl.fromLocalFile(view["media_path"]))
            if self.autoplay:
                self.player.play()
        self._load_form()
        if not media_ok:
            QMessageBox.warning(self, "Média modifié", "Le SHA-256 du fichier ne correspond pas au manifeste. "
                                "La vidéo n'est pas chargée : enregistrez l'exclusion « sha256_mismatch ».")

    def step(self, delta: int):
        order = self.session.order
        index = (order.index(self.item_id) + delta) % len(order)
        self.open_item(order[index])

    # ------------------------------------------------------------------ form <-> record

    def _load_form(self):
        self._loading = True
        record = self.record
        for category, group in self.category_groups.items():
            group.setExclusive(False)
            for button in group.buttons():
                button.setChecked(button.property("state") == record["categories"][category])
            group.setExclusive(True)
        self.nudity_context.setCurrentText(record["nudity_context"] or "")
        self.events_list.clear()
        for event in record["events"]:
            self.events_list.addItem(f"{event['category']} : {event['start_seconds']:.1f} – {event['end_seconds']:.1f} s")
        self.watched.setChecked(record["watched_in_full"])
        self.listened.setChecked(record["audio_listened"])
        self.listened.setEnabled(self.view["has_audio"])
        self.escalation.setCurrentText(record["escalation"])
        self.exclusion.setCurrentText(record["exclusion_reason"])
        self.notes.setPlainText(record["notes"])
        self._loading = False
        self._refresh()

    def _collect(self):
        record = dict(self.record)
        record["categories"] = {c: (g.checkedButton().property("state") if g.checkedButton() else None)
                                for c, g in self.category_groups.items()}
        record["nudity_context"] = self.nudity_context.currentText() or None
        record["watched_in_full"] = self.watched.isChecked()
        record["audio_listened"] = self.listened.isChecked() if self.view["has_audio"] else False
        record["escalation"] = self.escalation.currentText()
        record["exclusion_reason"] = self.exclusion.currentText().strip()
        record["notes"] = self.notes.toPlainText()
        record["played_intervals"] = [[round(a, 3), round(b, 3)] for a, b in self.tracker.intervals]
        record["playback_coverage"] = round(self.coverage(), 4)
        elapsed = time.monotonic() - self.opened_at if self.opened_at else 0.0
        record["seconds_spent"] = round(self.record.get("seconds_spent", 0.0) + elapsed, 1)
        self.opened_at = time.monotonic()
        return record

    def _changed(self, *_):
        if getattr(self, "_loading", False):
            return
        self.record = self._collect()
        self._refresh()
        if self.state != "locked" or self.editing_locked:
            self.autosave.start()

    def _refresh(self):
        locked = self.state == "locked" and not self.editing_locked
        for widget in self.form_panel.findChildren(QWidget):  # navigation lives outside the form panel
            if not isinstance(widget, (QLabel, QGroupBox)):
                widget.setEnabled(not locked)
        self.amend_button.setEnabled(locked)
        self.listened.setEnabled(not locked and self.view["has_audio"])
        self.watched.setEnabled(not locked and (self.fully_played() or self.watched.isChecked()))
        nudity = self.record["categories"]["nudity"]
        self.nudity_context.setEnabled(not locked and nudity in ("present", "uncertain"))
        progress = self.session.progress()
        state = {"new": "nouvelle", "draft": "brouillon", "locked": "VERROUILLÉE"}[self.state]
        self.header.setText(f"Vidéo {self.view['position']} / {self.view['total']} · durée "
                            f"{self.view['duration_seconds']:.1f} s · audio : {'oui' if self.view['has_audio'] else 'non'}"
                            f" · état : {state} · verrouillées : {progress['locked']} / {progress['total']}")
        self.label_view.setText(f"Étiquette vidéo (règles du guide) : {LABEL_TEXT[video_label(self.record)]}")
        problems = validate(self.record)
        self.problems_view.setText("\n".join(f"• {p}" for p in problems))
        self.lock_button.setEnabled(not locked and not problems)
        self._update_time()

    # ------------------------------------------------------------------ events

    def add_event(self):
        start, end = round(self.event_start.value(), 1), round(self.event_end.value(), 1)
        self.record["events"] = [*self.record["events"], {"category": self.event_category.currentText(),
                                                          "start_seconds": start, "end_seconds": end}]
        self._load_form()
        self._changed()

    def remove_event(self):
        row = self.events_list.currentRow()
        if row >= 0:
            events = list(self.record["events"])
            del events[row]
            self.record["events"] = events
            self._load_form()
            self._changed()

    # ------------------------------------------------------------------ playback

    def toggle_play(self):
        if self.player.source().isEmpty():
            return
        playing = self.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState
        self.player.pause() if playing else self.player.play()

    def seek_relative(self, seconds: float):
        self.seek_to(max(0, self.player.position() + int(seconds * 1000)))

    def seek_to(self, ms: int):
        self.tracker.interrupt()  # skipped content is never counted
        self.player.setPosition(int(ms))

    def set_rate(self, text: str):
        self.tracker.interrupt()
        self.player.setPlaybackRate(float(text.rstrip("×")))

    def position(self) -> float:
        return round(self.player.position() / 1000, 1)

    def _position_changed(self, ms: int):
        self.slider.blockSignals(True)
        self.slider.setValue(ms)
        self.slider.blockSignals(False)
        if self.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
            self.observe(ms / 1000, time.monotonic(), self.player.playbackRate())
        self._update_time()

    def observe(self, seconds: float, wall: float, rate: float):
        """One position report while playing; only steps consistent with real playback count."""
        if self.tracker.observe(seconds, wall, rate) and self.record is not None:
            self.record["played_intervals"] = [list(i) for i in self.tracker.intervals]
            self.record["playback_coverage"] = round(self.coverage(), 4)
            editable = self.state != "locked" or self.editing_locked
            self.watched.setEnabled(editable and (self.fully_played() or self.watched.isChecked()))

    def coverage(self) -> float:
        return covered_seconds(self.tracker.intervals, self.view["duration_seconds"]) / self.view["duration_seconds"]

    def fully_played(self) -> bool:
        return fully_played(self.tracker.intervals, self.view["duration_seconds"])

    def _update_time(self):
        self.time_label.setText(f"{self.player.position() / 1000:.1f} / {self.view['duration_seconds']:.1f} s")
        remaining = unplayed_seconds(self.tracker.intervals, self.view["duration_seconds"])
        self.coverage_label.setText(f"lu : {self.coverage():.0%} · non lu : {remaining:.1f} s"
                                    + (" (complet)" if remaining <= TIMING_TOLERANCE_SECONDS else ""))

    # ------------------------------------------------------------------ escalation, save, lock

    def emergency_stop(self):
        self.player.stop()
        self.player.setSource(QUrl())
        if self.escalation.currentText() == "none":
            choice, ok = QInputDialog.getItem(self, "Escalade", "Motif :", list(ESCALATIONS[1:]), 0, False)
            if not ok:
                return
            self.escalation.setCurrentText(choice)
        if not self.exclusion.currentText().strip():
            self.exclusion.setCurrentText(self.escalation.currentText())

    def _escalation_changed(self, *_):
        if self.escalation.currentText() != "none":
            self.player.stop()
            self.player.setSource(QUrl())
        self._changed()

    def save_draft(self):
        if self.record is None or (self.state == "locked" and not self.editing_locked):
            return
        self.record = self._collect()
        if self.state == "locked":
            return  # an amendment is kept in memory until it is locked as a new version
        self.session.save_draft(self.record)
        self.state = "draft"

    def lock(self):
        self.record = self._collect()
        reason = ""
        if self.editing_locked:
            reason, ok = QInputDialog.getText(self, "Correction", "Motif de la correction :")
            if not ok or not reason.strip():
                return
        elif QMessageBox.question(self, "Verrouiller", f"Verrouiller avec l'étiquette "
                                  f"{LABEL_TEXT[video_label(self.record)]} ? Elle ne sera plus modifiable, sauf par "
                                  "une correction motivée.") != QMessageBox.StandardButton.Yes:
            return
        try:
            self.session.lock(self.record, amendment_reason=reason)
        except (ValueError, LockedError) as exc:
            QMessageBox.warning(self, "Verrouillage refusé", str(exc))
            return
        self.state, self.editing_locked = "locked", False
        self._refresh()
        upcoming = self.session.progress()["next"]
        if upcoming is not None:
            self.open_item(upcoming)

    def start_amendment(self):
        self.editing_locked = True
        self._refresh()

    def closeEvent(self, event):
        self.save_draft()
        self.player.stop()
        self.player.setSource(QUrl())  # release the media file
        super().closeEvent(event)
