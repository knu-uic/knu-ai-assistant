import 'package:flutter/material.dart';

import 'splash_screen.dart';
import 'services/theme_service.dart';

void main() async {
  WidgetsFlutterBinding.ensureInitialized();
  await ThemeService.instance.loadTheme();
  runApp(const MyApp());
}

class MyApp extends StatelessWidget {
  const MyApp({super.key});

  @override
  Widget build(BuildContext context) {
    return ListenableBuilder(
      listenable: ThemeService.instance,
      builder: (context, _) {
        return MaterialApp(
          debugShowCheckedModeBanner: false,

          title: 'KNU AI Assistant',

          theme: ThemeData(
            colorScheme: ColorScheme.fromSeed(seedColor: Colors.blue),

            scaffoldBackgroundColor: Colors.grey.shade100,

            useMaterial3: true,
          ),

          darkTheme: ThemeData(
            colorScheme: ColorScheme.fromSeed(
              seedColor: Colors.blue,
              brightness: Brightness.dark,
            ),
            scaffoldBackgroundColor: Colors.grey.shade900,
            useMaterial3: true,
          ),

          themeMode: ThemeService.instance.themeMode,

          home: const SplashScreen(),
        );
      },
    );
  }
}
