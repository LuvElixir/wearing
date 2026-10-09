import {useLocalSearchParams} from 'expo-router';
import ExperienceScreen from '../../experience/ExperienceScreen';
import type {Page} from '../../experience/state';
export default function PageScreen(){const {page}=useLocalSearchParams<{page:string}>();return <ExperienceScreen page={page as Page}/>;}
