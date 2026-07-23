"use client";

/**
 * Landing page — présentation du projet GW2Analytics avec zone de
 * dépôt de fichiers .zevtc intégrée et accès rapide aux sections.
 */

import Link from "next/link";
import { useCallback, useEffect, useRef, useState } from "react";

import { uploadLog, formatApiError, type UploadCreatedRow } from "@/lib/api";
import { formatBytes } from "@/lib/format";

import styles from "./page.module.css";

const ACCEPTED_EXT = ".zevtc";
const MAX_UPLOAD_SIZE_BYTES = 100 * 1024 * 1024;

export default function Home() {
  const [dragOver, setDragOver] = useState(false);
  const [file, setFile] = useState<File | null>(null);
  const [rejected, setRejected] = useState<string | null>(null);
  const [uploading, setUploading] = useState(false);
  const [uploadResult, setUploadResult] = useState<UploadCreatedRow | null>(null);
  const [uploadError, setUploadError] = useState<string | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  const validateFile = useCallback((f: File): boolean => {
    if (!f.name.toLowerCase().endsWith(ACCEPTED_EXT)) {
      setRejected(`Seuls les fichiers ${ACCEPTED_EXT} sont acceptés.`);
      return false;
    }
    if (f.size > MAX_UPLOAD_SIZE_BYTES) {
      setRejected(
        `Fichier trop volumineux (${formatBytes(f.size)}). Maximum: ${formatBytes(MAX_UPLOAD_SIZE_BYTES)}.`,
      );
      return false;
    }
    return true;
  }, []);

  const handleFile = useCallback(
    (f: File | null) => {
      setRejected(null);
      setUploadResult(null);
      setUploadError(null);
      if (!f) {
        setFile(null);
        return;
      }
      if (validateFile(f)) {
        setFile(f);
      }
    },
    [validateFile],
  );

  const handleUpload = useCallback(async () => {
    if (!file) return;
    setUploading(true);
    setUploadError(null);
    try {
      const result = await uploadLog(file);
      setUploadResult(result);
      setFile(null);
    } catch (err) {
      setUploadError(formatApiError(err));
    } finally {
      setUploading(false);
    }
  }, [file]);

  const handleDrop = useCallback(
    (e: React.DragEvent) => {
      e.preventDefault();
      setDragOver(false);
      const dropped = e.dataTransfer.files?.[0] ?? null;
      handleFile(dropped);
    },
    [handleFile],
  );

  const handleDragOver = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    setDragOver(true);
  }, []);

  const handleDragLeave = useCallback(() => {
    setDragOver(false);
  }, []);

  return (
    <div className={styles.page}>
      {/* Hero */}
      <section className={styles.hero}>
        <span className={styles.brand}>Guild Wars 2 · WvW Analytics</span>
        <h1 className={styles.title}>GW2<span className={styles.accentText}>Analytics</span></h1>
        <p className={styles.tagline}>
          Analysez vos combats WvW en profondeur. Déposez vos logs{" "}
          <code>.zevtc</code> et obtenez instantanément un tableau de bord
          complet : dégâts, soins, boons, défense, positions et timeline.
        </p>
      </section>

      {/* Upload zone */}
      <section className={styles.uploadSection}>
        <div
          className={`${styles.dropZone} ${dragOver ? styles.dropZoneActive : ""} ${
            file || uploadResult ? styles.dropZoneHasFile : ""
          }`}
          onDrop={handleDrop}
          onDragOver={handleDragOver}
          onDragLeave={handleDragLeave}
          onClick={() => inputRef.current?.click()}
          role="button"
          tabIndex={0}
          aria-label="Zone de dépôt de fichier .zevtc"
          onKeyDown={(e) => {
            if (e.key === "Enter" || e.key === " ") {
              e.preventDefault();
              inputRef.current?.click();
            }
          }}
        >
          <input
            ref={inputRef}
            type="file"
            accept={ACCEPTED_EXT}
            className={styles.fileInputHidden}
            onChange={(e) => handleFile(e.currentTarget.files?.[0] ?? null)}
          />

          {uploadResult ? (
            <div className={styles.uploadResult}>
              <span className={styles.uploadSuccessIcon}>✅</span>
              <div>
                <p className={styles.uploadResultTitle}>Fichier importé !</p>
                <p className={styles.uploadResultId}>
                  ID: {uploadResult.id.slice(0, 8)}…
                </p>
                <Link
                  href={`/fights`}
                  className={styles.uploadResultLink}
                  onClick={(e) => e.stopPropagation()}
                >
                  Voir les combats →
                </Link>
              </div>
            </div>
          ) : uploading ? (
            <div className={styles.uploadingState}>
              <span className={styles.spinner} aria-hidden="true" />
              <span>Import en cours…</span>
            </div>
          ) : file ? (
            <div className={styles.fileSelected}>
              <span className={styles.fileIcon}>📄</span>
              <div>
                <p className={styles.fileName}>{file.name}</p>
                <p className={styles.fileSize}>{formatBytes(file.size)}</p>
              </div>
              <button
                className={styles.uploadButton}
                onClick={(e) => {
                  e.stopPropagation();
                  handleUpload();
                }}
                disabled={uploading}
              >
                Analyser
              </button>
            </div>
          ) : (
            <div className={styles.dropZonePlaceholder}>
              <span className={styles.dropIcon}>📂</span>
              <p className={styles.dropText}>
                {dragOver
                  ? "Déposez votre fichier ici"
                  : "Glissez-déposez votre log .zevtc ici"}
              </p>
              <p className={styles.dropHint}>
                ou cliquez pour parcourir (max {formatBytes(MAX_UPLOAD_SIZE_BYTES)})
              </p>
            </div>
          )}
        </div>

        {rejected && (
          <p className={styles.error} role="alert">
            {rejected}
          </p>
        )}
        {uploadError && (
          <p className={styles.error} role="alert">
            {uploadError}
          </p>
        )}
      </section>

      {/* Quick links */}
      {/*
       * ``data-testid="home-nav-*"`` attrs are stable selectors for the
       * Playwright e2e suite. They intentionally bypass the visible
       * French card title so the user-journey / landing specs do not
       * regress on a future copy rename or i18n pass. The same ``nav-*``
       * prefix on the global sticky header (see ``web/src/components/AppShell*``)
       * refers to the always-present header navigation, not these
       * feature cards, so the ``home-nav-*`` distinction matters.
       */}
      <nav className={styles.cards}>
        <Link className={styles.card} href="/fights" data-testid="home-nav-fights">
          <span className={styles.cardIcon}>⚔️</span>
          <span className={styles.cardTitle}>Combats</span>
          <span className={styles.cardBody}>
            Parcourez les combats parsés, inspectez les joueurs, les skills,
            et les timelines détaillées.
          </span>
          <span className={styles.cardArrow}>Explorer &rarr;</span>
        </Link>
        <Link className={styles.card} href="/players" data-testid="home-nav-players">
          <span className={styles.cardIcon}>👥</span>
          <span className={styles.cardTitle}>Joueurs</span>
          <span className={styles.cardBody}>
            Statistiques cross-combat de chaque compte : dégâts, soins,
            buff removal, et évolution dans le temps.
          </span>
          <span className={styles.cardArrow}>Voir &rarr;</span>
        </Link>
        <Link className={styles.card} href="/players/compare" data-testid="home-nav-compare">
          <span className={styles.cardIcon}>📊</span>
          <span className={styles.cardTitle}>Comparer</span>
          <span className={styles.cardBody}>
            Comparez les performances de deux joueurs côte à côte sur
            plusieurs combats.
          </span>
          <span className={styles.cardArrow}>Comparer &rarr;</span>
        </Link>
        <Link className={styles.card} href="/upload" data-testid="home-nav-upload">
          <span className={styles.cardIcon}>📤</span>
          <span className={styles.cardTitle}>Upload avancé</span>
          <span className={styles.cardBody}>
            Assistant d&apos;import complet avec suivi du parsing,
            historique et gestion des erreurs.
          </span>
          <span className={styles.cardArrow}>Ouvrir &rarr;</span>
        </Link>
      </nav>

      {/* Stats / features row */}
      <section className={styles.features}>
        <div className={styles.feature}>
          <span className={styles.featureValue}>Parser local</span>
          <span className={styles.featureLabel}>
            Les logs .zevtc sont parsés sur votre infrastructure, aucune donnée
            envoyée à un tiers.
          </span>
        </div>
        <div className={styles.feature}>
          <span className={styles.featureValue}>Analyse complète</span>
          <span className={styles.featureLabel}>
            Dégâts (power/condi), soins, barrière, boons, défense, positions,
            timeline — tout est calculé.
          </span>
        </div>
        <div className={styles.feature}>
          <span className={styles.featureValue}>Cross-fight</span>
          <span className={styles.featureLabel}>
            Les profils joueurs agrègent les stats sur tous les combats pour
            une vue d&apos;ensemble.
          </span>
        </div>
      </section>
    </div>
  );
}
