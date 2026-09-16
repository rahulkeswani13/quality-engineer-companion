import { useMemo, useRef } from "react";
import type * as THREE from "three";
import { Canvas, useFrame } from "@react-three/fiber";
import { Grid, Html, OrbitControls } from "@react-three/drei";
import styles from "./City.module.css";
import {
  CITY_EDGES,
  CITY_NODES,
  TOKENS,
  activeEdges,
  nodeById,
  type CityEdge,
  type CityNode,
} from "./topology";

type Tone = "neutral" | "wait" | "refuse" | "write";

const TONE_COLOR: Record<Tone, string> = {
  neutral: TOKENS.ok,
  wait: TOKENS.tag,
  refuse: TOKENS.stamp,
  write: TOKENS.ok,
};

function kindTone(kind: CityNode["kind"]): Tone {
  if (kind === "interrupt") return "wait";
  if (kind === "refuse") return "refuse";
  return "neutral";
}

/** Pulse/spin marker above whichever node the graph currently occupies. */
function Beacon({ node, tone }: { node: CityNode; tone: Tone }) {
  const ref = useRef<THREE.Mesh>(null!);
  const color = TONE_COLOR[tone];
  useFrame((state) => {
    const t = state.clock.elapsedTime;
    const s = 1 + 0.14 * Math.sin(t * 3.4);
    ref.current.scale.setScalar(s);
    ref.current.rotation.y = t * 1.1;
  });
  return (
    <mesh ref={ref} position={[node.pos[0], node.h + 1.05, node.pos[1]]}>
      <octahedronGeometry args={[0.42]} />
      <meshStandardMaterial
        color={color}
        emissive={color}
        emissiveIntensity={0.85}
        roughness={0.35}
      />
    </mesh>
  );
}

function Building({
  node,
  visited,
  isCurrent,
  selected,
  onSelect,
}: {
  node: CityNode;
  visited: boolean;
  isCurrent: boolean;
  selected: boolean;
  onSelect: (id: string) => void;
}) {
  const tone = kindTone(node.kind);
  const ghost = !visited;
  const emissive = isCurrent
    ? node.kind === "interrupt"
      ? { c: TOKENS.tag, i: 0.5 }
      : node.kind === "refuse"
        ? { c: TOKENS.stamp, i: 0.45 }
        : { c: TOKENS.ok, i: 0.3 }
    : null;
  return (
    <group>
      <mesh
        position={[node.pos[0], node.h / 2, node.pos[1]]}
        onClick={(e) => {
          e.stopPropagation();
          onSelect(node.id);
        }}
      >
        <boxGeometry args={[1.9, node.h, 1.9]} />
        <meshStandardMaterial
          color={TOKENS.ink}
          transparent={ghost}
          opacity={ghost ? 0.16 : 1}
          roughness={0.85}
          emissive={emissive?.c ?? TOKENS.ink}
          emissiveIntensity={emissive?.i ?? 0}
        />
      </mesh>
      {/* roof slab */}
      <mesh position={[node.pos[0], node.h + 0.09, node.pos[1]]}>
        <boxGeometry args={[2.3, 0.18, 2.3]} />
        <meshStandardMaterial
          color={visited ? TOKENS.rule : TOKENS.ink}
          transparent={ghost}
          opacity={ghost ? 0.12 : 1}
          roughness={0.9}
        />
      </mesh>
      {selected && (
        <mesh position={[node.pos[0], node.h / 2, node.pos[1]]}>
          <boxGeometry args={[2.12, node.h + 0.24, 2.12]} />
          <meshBasicMaterial color={TONE_COLOR[tone]} wireframe />
        </mesh>
      )}
      <Html
        center
        distanceFactor={26}
        position={[node.pos[0], node.h + 0.95, node.pos[1]]}
        zIndexRange={[20, 10]}
      >
        <div
          className={`${styles.label} ${selected ? styles.labelActive : ""}`}
          onClick={() => onSelect(node.id)}
        >
          {node.name}
        </div>
      </Html>
    </group>
  );
}

function Road({
  edge,
  lit,
  tone,
}: {
  edge: CityEdge;
  lit: boolean;
  tone: Tone;
}) {
  const a = nodeById(edge.from);
  const b = nodeById(edge.to);
  const geom = useMemo(() => {
    if (!a || !b) return null;
    const dx = b.pos[0] - a.pos[0];
    const dz = b.pos[1] - a.pos[1];
    const len = Math.hypot(dx, dz);
    return {
      cx: a.pos[0] + dx / 2,
      cz: a.pos[1] + dz / 2,
      len,
      rotY: Math.atan2(-dz, dx),
    };
  }, [a, b]);
  if (!geom) return null;
  const narrow = edge.kind !== "main";
  const width = narrow ? 0.7 : 1.15;
  const litColor = TONE_COLOR[tone];
  return (
    <group>
      <mesh position={[geom.cx, 0.03, geom.cz]} rotation={[0, geom.rotY, 0]}>
        <boxGeometry args={[geom.len, 0.05, width]} />
        <meshStandardMaterial
          color={TOKENS.rule}
          transparent
          opacity={edge.kind === "main" ? 0.55 : 0.3}
          roughness={0.95}
        />
      </mesh>
      {lit && (
        <>
          <mesh position={[geom.cx, 0.075, geom.cz]} rotation={[0, geom.rotY, 0]}>
            <boxGeometry args={[geom.len, 0.04, width * 0.62]} />
            <meshStandardMaterial
              color={litColor}
              emissive={litColor}
              emissiveIntensity={0.55}
              roughness={0.4}
            />
          </mesh>
          {edge.label && (
            <Html
              center
              distanceFactor={30}
              position={[geom.cx, 0.5, geom.cz]}
              zIndexRange={[20, 10]}
              style={{ pointerEvents: "none" }}
            >
              <div className={`${styles.edgeLabel} ${styles[`edge_${edge.kind}`]}`}>
                {edge.label}
              </div>
            </Html>
          )}
        </>
      )}
    </group>
  );
}

/** The human toll gate sits across the road into the records vault. */
function TollGate({
  closed,
  approved,
}: {
  closed: boolean;
  approved: boolean;
}) {
  const a = nodeById("wait_human");
  const b = nodeById("apply_or_escalate");
  const bar = useRef<THREE.Group>(null!);
  const geom = useMemo(() => {
    if (!a || !b) return null;
    const dx = b.pos[0] - a.pos[0];
    const dz = b.pos[1] - a.pos[1];
    return {
      cx: a.pos[0] + dx * 0.55,
      cz: a.pos[1] + dz * 0.55,
      rotY: Math.atan2(-dz, dx),
    };
  }, [a, b]);
  useFrame((_, delta) => {
    // Closed = bar level (blocking). Open = lifted like a crossing barrier.
    const target = closed ? 0 : -1.25;
    const next = bar.current.rotation.z + (target - bar.current.rotation.z) * Math.min(1, delta * 4);
    bar.current.rotation.z = next;
  });
  if (!geom) return null;
  const barColor = closed ? TOKENS.tag : approved ? TOKENS.ok : TOKENS.rule;
  return (
    <group position={[geom.cx, 0, geom.cz]} rotation={[0, geom.rotY, 0]}>
      {[-1.35, 1.35].map((x) => (
        <mesh key={x} position={[x, 0.55, 0]}>
          <boxGeometry args={[0.22, 1.1, 0.22]} />
          <meshStandardMaterial color={TOKENS.ink} roughness={0.8} />
        </mesh>
      ))}
      <group ref={bar} position={[0, 1.02, 0]}>
        <mesh position={[0, 0, 0]}>
          <boxGeometry args={[2.9, 0.22, 0.22]} />
          <meshStandardMaterial
            color={barColor}
            emissive={closed ? TOKENS.tag : TOKENS.ok}
            emissiveIntensity={closed ? 0.6 : 0.2}
            roughness={0.4}
          />
        </mesh>
      </group>
      <Html
        center
        distanceFactor={26}
        position={[0, 2.1, 0]}
        zIndexRange={[20, 10]}
        style={{ pointerEvents: "none" }}
      >
        <div className={styles.gateLabel}>
          {closed ? "toll gate — waiting for your decision" : "toll gate — released"}
        </div>
      </Html>
    </group>
  );
}

/** Small work-order cube that keeps travelling the most recent leg. */
function Courier({ fromId, toId }: { fromId: string; toId: string }) {
  const ref = useRef<THREE.Mesh>(null!);
  const a = nodeById(fromId);
  const b = nodeById(toId);
  useFrame((state) => {
    if (!a || !b) return;
    const t = (state.clock.elapsedTime * 0.45) % 1;
    ref.current.position.set(
      a.pos[0] + (b.pos[0] - a.pos[0]) * t,
      0.42 + 0.12 * Math.sin(state.clock.elapsedTime * 6),
      a.pos[1] + (b.pos[1] - a.pos[1]) * t,
    );
    ref.current.rotation.y = state.clock.elapsedTime * 2;
  });
  if (!a || !b) return null;
  return (
    <mesh ref={ref}>
      <boxGeometry args={[0.5, 0.5, 0.5]} />
      <meshStandardMaterial color={TOKENS.ink} roughness={0.5} />
    </mesh>
  );
}

export type CityStatus =
  | "idle"
  | "running"
  | "waiting_human"
  | "done"
  | "rejected"
  | "abstained"
  | "failed";

export default function CityView({
  visited,
  status,
  lotId,
  onSelectNode,
  selectedId,
}: {
  /** Ordered node visits including the rewrite loop repeats. */
  visited: string[];
  status: CityStatus;
  lotId: string | null;
  onSelectNode: (id: string | null) => void;
  selectedId: string | null;
}) {
  const lit = useMemo(() => activeEdges(visited), [visited]);
  const currentId = visited.length > 0 ? visited[visited.length - 1] : null;
  const lastLeg =
    visited.length >= 2 ? { fromId: visited[visited.length - 2], toId: currentId! } : null;
  const waiting = status === "waiting_human";
  const approved = ["done", "rejected"].includes(status);
  const picked = selectedId ? nodeById(selectedId) : undefined;

  function toggleNode(id: string) {
    onSelectNode(selectedId === id ? null : id);
  }

  const statusWord: Record<CityStatus, string> = {
    idle: "Idle — pick a scenario and press Run",
    running: "Work order in transit…",
    waiting_human: "Stopped at the human toll gate",
    done: "Containment written to the records vault",
    rejected: "Rejected — routed out with no write",
    abstained: "Refused — nothing grounded, no write",
    failed: "Failed loudly before any write",
  };

  return (
    <div className={styles.wrap}>
      <div className={styles.canvasHost}>
        <Canvas
          dpr={[1, 2]}
          gl={{ alpha: true }}
          camera={{ position: [4, 24, 34], fov: 38 }}
          // Only clear selection for real canvas clicks; clicks on the DOM
          // label overlays must not wipe a just-selected building.
          onPointerMissed={(e) => {
            const target = e.target as HTMLElement | null;
            if (!target || target.tagName === "CANVAS") onSelectNode(null);
          }}
        >
          <fog attach="fog" args={[TOKENS.paper, 58, 120]} />
          <hemisphereLight args={[TOKENS.paper, TOKENS.ink, 1.15]} />
          <directionalLight position={[18, 30, 12]} intensity={1.1} />
          <Grid
            infiniteGrid
            cellSize={2}
            sectionSize={10}
            cellColor={TOKENS.rule}
            sectionColor={TOKENS.rule}
            cellThickness={0.6}
            sectionThickness={1.1}
            fadeDistance={105}
            fadeStrength={1.4}
            position={[0, 0.005, 0]}
          />
          {CITY_EDGES.map((e) => (
            <Road
              key={`${e.from}->${e.to}`}
              edge={e}
              lit={lit.has(`${e.from}->${e.to}`)}
              tone={e.kind === "refuse" ? "refuse" : "neutral"}
            />
          ))}
          {CITY_NODES.map((n) => (
            <Building
              key={n.id}
              node={n}
              visited={
                n.id === "start_sign" || visited.includes(n.id)
                }
              isCurrent={currentId === n.id}
              selected={selectedId === n.id}
              onSelect={toggleNode}
            />
          ))}
          <TollGate closed={waiting} approved={approved} />
          {lastLeg && status === "running" && (
            <Courier fromId={lastLeg.fromId} toId={lastLeg.toId} />
          )}
          {currentId && nodeById(currentId) && (
            <Beacon
              node={nodeById(currentId)!}
              tone={
                waiting
                  ? "wait"
                  : currentId === "abstain" || status === "rejected" || status === "failed"
                    ? "refuse"
                    : "neutral"
              }
            />
          )}
          <OrbitControls
            makeDefault
            target={[0, 1, 2]}
            minDistance={12}
            maxDistance={78}
            maxPolarAngle={Math.PI / 2 - 0.07}
            enablePan
          />
        </Canvas>
      </div>

      <div className={styles.statusStrip}>
        <span className={styles.stripStatus} data-status={status}>
          {statusWord[status]}
        </span>
        {lotId && <span className={styles.stripLot}>lot {lotId}</span>}
        {visited.length > 0 && (
          <span className={styles.stripSteps}>{visited.length} steps</span>
        )}
      </div>

      <div className={styles.legendStack}>
        <div className={styles.legend} aria-label="Route legend">
          <span className={styles.legendItem}>
            <i className={styles.swatchOk} /> taken path
          </span>
          <span className={styles.legendItem}>
            <i className={styles.swatchTag} /> waiting on human
          </span>
          <span className={styles.legendItem}>
            <i className={styles.swatchStamp} /> refused / no write
          </span>
          <span className={styles.legendItem}>
            <i className={styles.swatchRule} /> paved, not taken
          </span>
        </div>
        {picked && (
          <div className={styles.inspect} aria-label="Selected node">
            <p className={styles.inspectName}>{picked.name}</p>
            <p className={styles.inspectId}>{picked.id}</p>
            <p className={styles.inspectBlurb}>{picked.blurb}</p>
          </div>
        )}
      </div>

      <p className={styles.hint}>Drag to orbit · scroll to zoom · click a building · click again to close</p>
    </div>
  );
}
