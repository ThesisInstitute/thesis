export function DemoVideo({
  caption,
}: {
  caption?: string;
}) {
  const assetRev = process.env.NEXT_PUBLIC_SITE_ASSET_REV || "dev";
  const videoSrc = `/demo/brier-demo.mp4?v=${assetRev}`;
  const posterSrc = `/demo/brier-demo-poster.png?v=${assetRev}`;

  return (
    <figure className="m-0">
      <div className="rounded-[28px] overflow-hidden border border-[#E7E5E4] bg-white shadow-[0_20px_50px_rgba(28,25,23,0.12)]">
        <video
          className="block w-full h-auto"
          autoPlay
          controls
          loop
          muted
          playsInline
          poster={posterSrc}
          preload="metadata"
          aria-label="End-to-end brier workflow demo for Codex"
        >
          <source src={videoSrc} type="video/mp4" />
        </video>
      </div>
      <figcaption className="mt-4 space-y-3">
        {caption ? (
          <p className="m-0 text-[0.82rem] text-[#78716C] leading-[1.6]">
            {caption}
          </p>
        ) : null}
        <div className="flex flex-wrap gap-x-5 gap-y-2 text-[0.8rem] [font-family:var(--font-mono)]">
          <a
            href={videoSrc}
            target="_blank"
            rel="noreferrer"
            className="text-[#57534E] underline decoration-[#D6D3D1] underline-offset-4 hover:text-[#1C1917] hover:decoration-[#1C1917]"
          >
            Open 4K MP4
          </a>
          <a
            href={posterSrc}
            target="_blank"
            rel="noreferrer"
            className="text-[#57534E] underline decoration-[#D6D3D1] underline-offset-4 hover:text-[#1C1917] hover:decoration-[#1C1917]"
          >
            Open poster
          </a>
        </div>
      </figcaption>
    </figure>
  );
}
