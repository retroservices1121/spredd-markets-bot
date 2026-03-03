import React, { useState } from "react";
import { View, Text, Pressable, Dimensions } from "react-native";
import { useRouter } from "expo-router";
import { useSafeAreaInsets } from "react-native-safe-area-context";
import Animated, {
  FadeIn,
  FadeOut,
  SlideInRight,
  SlideOutLeft,
} from "react-native-reanimated";
import { ChevronRight } from "lucide-react-native";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

const { width } = Dimensions.get("window");

const slides = [
  {
    title: "Predict the Future",
    subtitle:
      "Trade on real-world events across multiple prediction markets",
  },
  {
    title: "Swipe & Trade",
    subtitle:
      "Discover trending markets with a simple swipe \u2014 buy Yes or No in seconds",
  },
  {
    title: "Track & Win",
    subtitle:
      "Monitor your portfolio, climb the leaderboard, and earn rewards",
  },
];

export default function WelcomePage() {
  const [currentSlide, setCurrentSlide] = useState(0);
  const router = useRouter();
  const insets = useSafeAreaInsets();

  const handleNext = () => {
    if (currentSlide < slides.length - 1) {
      setCurrentSlide(currentSlide + 1);
    } else {
      router.replace("/(auth)/login");
    }
  };

  return (
    <View
      className="flex-1 bg-spredd-bg"
      style={{ paddingTop: insets.top, paddingBottom: insets.bottom }}
    >
      {/* Slides */}
      <View className="flex-1 items-center justify-center px-8">
        <Text className="font-brand text-4xl text-spredd-green mb-12">
          SPREDD
        </Text>

        <Animated.View
          key={currentSlide}
          entering={FadeIn.duration(300)}
          exiting={FadeOut.duration(200)}
          className="items-center"
        >
          <Text className="text-3xl font-bold text-white text-center mb-4">
            {slides[currentSlide].title}
          </Text>
          <Text className="text-base text-white/60 text-center leading-6">
            {slides[currentSlide].subtitle}
          </Text>
        </Animated.View>
      </View>

      {/* Bottom controls */}
      <View className="px-6 pb-6 gap-6">
        {/* Dots */}
        <View className="flex-row justify-center gap-2">
          {slides.map((_, i) => (
            <View
              key={i}
              className={cn(
                "h-1.5 rounded-full transition-all",
                i === currentSlide
                  ? "w-8 bg-spredd-green"
                  : "w-1.5 bg-white/20"
              )}
            />
          ))}
        </View>

        <Button variant="default" size="lg" onPress={handleNext}>
          {currentSlide < slides.length - 1 ? "Next" : "Get Started"}
        </Button>

        {currentSlide < slides.length - 1 && (
          <Pressable
            onPress={() => router.replace("/(auth)/login")}
            className="items-center"
          >
            <Text className="text-sm text-white/40">Skip</Text>
          </Pressable>
        )}
      </View>
    </View>
  );
}
