import type { ButtonHTMLAttributes, ElementType, ReactNode } from 'react';
import { useEffect, useRef } from 'react';
import { TileArtwork } from './tile-artwork';
import { fpsReading, tileReadingView } from './tile-reading';
import type { TileReading } from './tile-reading';

type TileProps = {
  label: string;
  artworkId: string;
  Button?: ElementType;
  buttonProps?: ButtonHTMLAttributes<HTMLButtonElement> & Record<string, unknown>;
  children?: ReactNode;
  artwork?: ReactNode;
  unavailable?: boolean;
};

/** Uses the shell's existing card chrome; caller retains Decky focus/navigation props. */
export function ReGearTile({ label, artworkId, Button = 'button', buttonProps, children, artwork, unavailable }: TileProps) {
  return <Button {...buttonProps} type="button"
    className={['rg-expanded-tile', artwork && 'rg-v3-tile', buttonProps?.className].filter(Boolean).join(' ')}
    aria-disabled={unavailable || buttonProps?.['aria-disabled']}
    onClick={unavailable ? undefined : buttonProps?.onClick}
    onOKButton={unavailable ? undefined : buttonProps?.onOKButton}>
    {artwork}
    <span className={artwork ? 'rg-expanded-tile-body rg-v3-tile-copy' : 'rg-expanded-tile-body'}>
      <span className="rg-expanded-tile-heading">
        {!artwork && <span className="rg-expanded-tile-icon"><TileArtwork id={artworkId}/></span>}
        <span className="rg-expanded-label">{label}</span>
      </span>
      {children}
    </span>
  </Button>;
}

export function StaticActionTile({ readiness, ...props }: Omit<TileProps, 'children'> & { readiness?: 'Ready' | 'Unavailable' }) {
  return <ReGearTile {...props} unavailable={props.unavailable || readiness === 'Unavailable'}>
    {readiness && <span className="rg-tile-metadata">{readiness}</span>}
  </ReGearTile>;
}

/** Mount once alongside TileArtworkSprite. Motion runs only when readings change. */
export const tileOverlayStyles = `
.rg-tile-metadata{display:block;font-size:.75em;line-height:1.15;overflow-wrap:anywhere}
.rg-tile-gauge{width:48px;height:32px;display:block;overflow:visible}
.rg-tile-gauge-track{stroke:#315c75}.rg-tile-gauge-fill{stroke:#32d7ff;transition:stroke-dashoffset 250ms ease}
.rg-tile-gauge[data-known=false]{opacity:.3}
.rg-expanded .rg-expanded-tile.rg-v3-tile{position:relative;isolation:isolate;overflow:hidden;padding:0!important;text-align:left;aspect-ratio:5/3;height:auto!important;min-height:0!important;max-height:none!important}
.rg-v3-tile-artwork{position:absolute;inset:0;z-index:0;width:100%;height:100%;display:block;object-fit:fill;pointer-events:none}
.rg-expanded-tile .rg-v3-tile-copy{position:relative;z-index:1;width:58%;height:100%;padding:7px 2px 7px 9px;align-items:flex-start;justify-content:center;gap:3px;text-align:left;text-shadow:0 1px 2px #000}
.rg-v3-tile-copy .rg-expanded-tile-heading{justify-content:flex-start;text-align:left}
.rg-v3-tile-copy .rg-expanded-label,.rg-v3-tile-copy .rg-expanded-value,.rg-v3-tile-copy .rg-tile-metadata{max-width:100%;text-align:left}
.rg-v3-tile-copy .rg-expanded-value{font-size:clamp(10px,1vw,14px);white-space:normal;overflow-wrap:anywhere}
.rg-v3-tile[data-tone=unavailable] .rg-expanded-value{color:#dbeeff;text-shadow:0 1px 2px #000}
.rg-expanded-tile.rg-v3-tile:focus-visible{outline:2px solid #8cecff;outline-offset:-3px;box-shadow:0 0 0 2px #061521,0 0 13px #28d9ff99}
@media(prefers-reduced-motion:reduce){.rg-tile-gauge-fill{transition:none}}
`;

export function DynamicTile({ reading, gauge = false, ...props }: Omit<TileProps, 'children'> & { reading: TileReading; gauge?: boolean }) {
  const view = tileReadingView(reading);
  const previousProgress = useRef<number | null>(null);
  const interpolate = view.progress !== null && previousProgress.current !== null;
  useEffect(() => { previousProgress.current = view.progress; }, [view.progress]);
  return <ReGearTile {...props} unavailable={props.unavailable}>
    <span className="rg-expanded-value">{view.primary}{view.unit && <> {view.unit}</>}</span>
    {view.secondary && <span className="rg-tile-metadata">{view.secondary}</span>}
    {view.status && <span className="rg-tile-metadata">{view.status}</span>}
    {(reading.freshness || reading.confidence) && <span className="rg-tile-metadata">
      {[reading.freshness, reading.confidence].filter(Boolean).join(' · ')}
    </span>}
    {gauge && <svg className="rg-tile-gauge" viewBox="0 0 48 32" aria-hidden="true" data-known={view.progress !== null}>
      <path className="rg-tile-gauge-track" d="M4 26a20 20 0 1 1 40 0" fill="none" strokeWidth="4"/>
      <path className="rg-tile-gauge-fill" d="M4 26a20 20 0 1 1 40 0" fill="none" strokeWidth="4" pathLength="1"
        strokeDasharray="1" strokeDashoffset={1 - (view.progress ?? 0)}
        style={!interpolate ? { transition: 'none' } : undefined}/>
    </svg>}
  </ReGearTile>;
}

export function FpsTile({ current, target, evidence, ...props }: Omit<TileProps, 'children' | 'artworkId'> & {
  current?: number | null; target?: number | null;
  evidence: Pick<TileReading, 'availability' | 'freshness' | 'confidence'>;
}) {
  return <DynamicTile {...props} artworkId="fps" reading={fpsReading(current, target, evidence)} gauge/>;
}
