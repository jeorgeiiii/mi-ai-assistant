'use client';

import { useEffect, useState } from 'react';
import { withParams } from '@/app/themes';

const ROTATE_INTERVAL_MS = 3 * 60 * 1000;
const TRANSITION_MS = 2500;

interface BackgroundSlideshowProps {
  images: string[];
}

export default function BackgroundSlideshow({ images }: BackgroundSlideshowProps) {
  const [activeIndex, setActiveIndex] = useState(0);

  useEffect(() => {
    setActiveIndex(0);
  }, [images]);

  useEffect(() => {
    if (images.length <= 1) return;
    const id = setInterval(() => {
      setActiveIndex((prev) => (prev + 1) % images.length);
    }, ROTATE_INTERVAL_MS);
    return () => clearInterval(id);
  }, [images]);

  return (
    <div className="fixed inset-0 -z-10 overflow-hidden bg-gray-900">
      {images.map((src, index) => (
        <div
          key={src}
          className="absolute inset-0 bg-cover bg-center"
          style={{
            backgroundImage: `url(${withParams(src, 1920)})`,
            opacity: index === activeIndex ? 1 : 0,
            transition: `opacity ${TRANSITION_MS}ms ease-in-out`,
          }}
        />
      ))}
      <div className="absolute inset-0 bg-gradient-to-b from-black/40 via-black/30 to-black/50" />
    </div>
  );
}
