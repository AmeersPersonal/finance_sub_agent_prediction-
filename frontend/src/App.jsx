import { useState } from 'react'
import {Routes, Route} from 'react-router-dom'
import Landing from "./pages/Landing"
import Signin from "./pages/Signin"
import Signup from "./pages/Signup"
import Dashboard from "./pages/Dashboard"
import './App.css'

function App() {
  const [count, setCount] = useState(0)
  
  return (
    <>
     <Routes>
      <Route path = "/" element = {<Landing/>}/>
      <Route path = "/Signin" element = {<Signin/>}/>
       <Route path = "/Signup" element = {<Signup/>}/> 
      <Route path = "/Dashboard" element = {<Dashboard/>}/>
      
     </Routes>
    
    </>
  )
}

export default App
